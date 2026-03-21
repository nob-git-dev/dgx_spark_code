# ハードウェア仕様

## マシン

- **製品名:** NVIDIA DGX Spark（または互換機）
- **ホスト名:** {{HOSTNAME}}
- **OS:** Ubuntu 24.04 LTS
- **カーネル:** {{KERNEL_VERSION}} (aarch64)

## CPU

- **SoC:** NVIDIA GB10
- **構成:** ARM big.LITTLE — Cortex-X925 (10コア, 最大3.9GHz) + Cortex-A725 (10コア, 最大2.8GHz)
- **合計:** 20コア / 20スレッド
- **アーキテクチャ:** aarch64（ARM64）— x86バイナリは動作しない
- **ISA拡張:** SVE, SVE2, BF16, I8MM, SHA-512

## GPU

- **GPU:** NVIDIA Blackwell（GB10 統合GPU）
- **ドライバ:** {{DRIVER_VERSION}}（Open Kernel Module）
- **CUDA:** {{CUDA_VERSION}}

## メモリ

- **合計:** 128GB 統合メモリ（CPU/GPU共有、LPDDR5x）
- **OS表示:** 約121GiB（カーネル予約分を除く）
- **Swap:** {{SWAP_SIZE}}

## ストレージ

- **NVMe:** {{STORAGE_SIZE}}（{{STORAGE_DEVICE}}）
  - `/boot/efi` — 512MB
  - `/` — {{ROOT_SIZE}}（使用 {{USED}} / 空き {{FREE}}）
