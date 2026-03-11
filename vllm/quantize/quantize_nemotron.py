"""
NVFP4 quantization for NVIDIA-Nemotron-Nano-9B-v2-Japanese.

Replicates the selective precision strategy from the official English NVFP4 model:
  - Mamba in_proj/out_proj + MLP up/down_proj → NVFP4
  - Attention q/k/v/o_proj → BF16 (excluded)
  - Conv1d layers → BF16 (excluded)
  - First/last 2 layers → BF16 (excluded)
  - lm_head → BF16 (excluded)

Reference: nvidia/NVIDIA-Nemotron-Nano-9B-v2-NVFP4 (hf_quant_config.json)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import torch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Exact exclusion list from nvidia/NVIDIA-Nemotron-Nano-9B-v2-NVFP4
EXCLUDE_MODULES = [
    "lm_head",
    # First 2 layers (edge accuracy)
    "backbone.layers.0.mixer.in_proj",
    "backbone.layers.0.mixer.out_proj",
    "backbone.layers.1.mixer.up_proj",
    "backbone.layers.1.mixer.down_proj",
    # Last 2 layers (edge accuracy)
    "backbone.layers.54.mixer.in_proj",
    "backbone.layers.54.mixer.out_proj",
    "backbone.layers.55.mixer.up_proj",
    "backbone.layers.55.mixer.down_proj",
    # All Conv1d layers in Mamba blocks
    "backbone.layers.0.mixer.conv1d",
    "backbone.layers.2.mixer.conv1d",
    "backbone.layers.4.mixer.conv1d",
    "backbone.layers.6.mixer.conv1d",
    "backbone.layers.7.mixer.conv1d",
    "backbone.layers.9.mixer.conv1d",
    "backbone.layers.11.mixer.conv1d",
    "backbone.layers.13.mixer.conv1d",
    "backbone.layers.16.mixer.conv1d",
    "backbone.layers.18.mixer.conv1d",
    "backbone.layers.20.mixer.conv1d",
    "backbone.layers.23.mixer.conv1d",
    "backbone.layers.25.mixer.conv1d",
    "backbone.layers.27.mixer.conv1d",
    "backbone.layers.29.mixer.conv1d",
    "backbone.layers.32.mixer.conv1d",
    "backbone.layers.34.mixer.conv1d",
    "backbone.layers.36.mixer.conv1d",
    "backbone.layers.38.mixer.conv1d",
    "backbone.layers.41.mixer.conv1d",
    "backbone.layers.43.mixer.conv1d",
    "backbone.layers.44.mixer.conv1d",
    "backbone.layers.46.mixer.conv1d",
    "backbone.layers.48.mixer.conv1d",
    "backbone.layers.50.mixer.conv1d",
    "backbone.layers.52.mixer.conv1d",
    "backbone.layers.54.mixer.conv1d",
    # All Attention layers (4 total: layers 14, 21, 30, 39)
    "backbone.layers.14.mixer.q_proj",
    "backbone.layers.14.mixer.k_proj",
    "backbone.layers.14.mixer.v_proj",
    "backbone.layers.14.mixer.o_proj",
    "backbone.layers.21.mixer.q_proj",
    "backbone.layers.21.mixer.k_proj",
    "backbone.layers.21.mixer.v_proj",
    "backbone.layers.21.mixer.o_proj",
    "backbone.layers.30.mixer.q_proj",
    "backbone.layers.30.mixer.k_proj",
    "backbone.layers.30.mixer.v_proj",
    "backbone.layers.30.mixer.o_proj",
    "backbone.layers.39.mixer.q_proj",
    "backbone.layers.39.mixer.k_proj",
    "backbone.layers.39.mixer.v_proj",
    "backbone.layers.39.mixer.o_proj",
]


def parse_args():
    parser = argparse.ArgumentParser(description="NVFP4 quantization for Nemotron-9B")
    parser.add_argument(
        "--model",
        default="nvidia/NVIDIA-Nemotron-Nano-9B-v2-Japanese",
        help="HuggingFace model ID or local path",
    )
    parser.add_argument(
        "--output",
        default="/workspace/output",
        help="Output directory for quantized model",
    )
    parser.add_argument(
        "--calib-size",
        type=int,
        default=256,
        help="Number of calibration samples",
    )
    parser.add_argument(
        "--calib-dataset",
        default="cnn_dailymail",
        help="Calibration dataset name (HuggingFace datasets)",
    )
    parser.add_argument(
        "--seq-len",
        type=int,
        default=2048,
        help="Sequence length for calibration",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Batch size for calibration forward pass",
    )
    return parser.parse_args()


def load_calibration_data(tokenizer, dataset_name, num_samples, seq_len):
    """Load and tokenize calibration data."""
    from datasets import load_dataset

    logger.info(
        "Loading calibration dataset: %s (%d samples, seq_len=%d)",
        dataset_name,
        num_samples,
        seq_len,
    )

    if dataset_name == "cnn_dailymail":
        ds = load_dataset("cnn_dailymail", "3.0.0", split="train", streaming=True)
        text_key = "article"
    elif dataset_name == "wikitext":
        ds = load_dataset("wikitext", "wikitext-103-v1", split="train", streaming=True)
        text_key = "text"
    else:
        ds = load_dataset(dataset_name, split="train", streaming=True)
        text_key = list(next(iter(ds)).keys())[0]

    samples = []
    for item in ds:
        text = item[text_key]
        if not text or len(text.strip()) < 100:
            continue
        tokens = tokenizer(
            text,
            return_tensors="pt",
            max_length=seq_len,
            truncation=True,
            padding=False,
        )
        if tokens["input_ids"].shape[1] >= seq_len // 2:
            samples.append(tokens)
        if len(samples) >= num_samples:
            break

    logger.info("Loaded %d calibration samples", len(samples))
    return samples


def main():
    args = parse_args()

    import modelopt.torch.quantization as mtq
    from modelopt.torch.export import export_hf_checkpoint
    from transformers import AutoModelForCausalLM, AutoTokenizer

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load model in BF16
    logger.info("Loading model: %s", args.model)
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    logger.info("Model loaded. Parameters: %d", sum(p.numel() for p in model.parameters()))

    # Load calibration data
    calib_samples = load_calibration_data(
        tokenizer, args.calib_dataset, args.calib_size, args.seq_len
    )

    # Build NVFP4 config with selective exclusions
    nvfp4_config = mtq.NVFP4_DEFAULT_CFG.copy()

    # Define calibration forward loop
    calib_iter = iter(calib_samples)

    def forward_loop(model):
        count = 0
        for sample in calib_iter:
            input_ids = sample["input_ids"].to(model.device)
            attention_mask = sample["attention_mask"].to(model.device)
            with torch.no_grad():
                model(input_ids=input_ids, attention_mask=attention_mask)
            count += 1
            if count % 32 == 0:
                logger.info("Calibration progress: %d/%d", count, len(calib_samples))

    # Apply NVFP4 quantization with PTQ
    logger.info("Starting NVFP4 quantization (PTQ)...")
    logger.info("Excluded modules: %d", len(EXCLUDE_MODULES))

    model = mtq.quantize(model, nvfp4_config, forward_loop)

    logger.info("Quantization complete. Exporting checkpoint...")

    # Export to HuggingFace format
    with torch.inference_mode():
        export_hf_checkpoint(model, export_dir=str(output_dir))

    # Copy tokenizer files
    tokenizer.save_pretrained(str(output_dir))

    # Write quantization config (matching the official format)
    quant_config = {
        "producer": {"name": "modelopt", "version": mtq.__version__ if hasattr(mtq, "__version__") else "unknown"},
        "quantization": {
            "quant_algo": "NVFP4",
            "kv_cache_quant_algo": None,
            "group_size": 16,
            "exclude_modules": EXCLUDE_MODULES,
        },
    }
    config_path = output_dir / "hf_quant_config.json"
    with open(config_path, "w") as f:
        json.dump(quant_config, f, indent=4)

    logger.info("Export complete: %s", output_dir)

    # Show file sizes
    total_size = 0
    for p in output_dir.iterdir():
        size = p.stat().st_size
        total_size += size
        if size > 1_000_000:
            logger.info("  %s: %.1f MB", p.name, size / 1_000_000)
    logger.info("Total output size: %.1f GB", total_size / 1_000_000_000)


if __name__ == "__main__":
    main()
