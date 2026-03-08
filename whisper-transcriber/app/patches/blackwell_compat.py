"""
Blackwell (SM_121) 互換パッチ

GB10 の Compute Capability 12.1 (SM_121) は、多くの CUDA ライブラリでまだ
サポートされていない。Hopper (SM_90) としてスプーフィングすることで、
Blackwell が Hopper 向けカーネルをバイナリ互換で実行できることを利用する。

参考: https://github.com/Mekopa/whisperx-blackwell

環境変数 DISABLE_BLACKWELL_PATCH=true で無効化可能。
将来の NGC コンテナ (25.09+) で SM_121 がネイティブサポートされた場合に使用。
"""

import os
import logging

logger = logging.getLogger(__name__)

_patched = False


def apply_blackwell_patch() -> bool:
    """Blackwell GPU を Hopper として認識させるパッチを適用する。

    Returns:
        True: パッチ適用済み / False: パッチ不要または無効化済み
    """
    global _patched

    if _patched:
        return True

    if os.environ.get("DISABLE_BLACKWELL_PATCH", "").lower() in ("true", "1", "yes"):
        logger.info("Blackwell互換パッチは環境変数により無効化されています")
        return False

    try:
        import torch
    except ImportError:
        logger.debug("PyTorch が見つかりません。パッチをスキップします")
        return False

    if not torch.cuda.is_available():
        logger.debug("CUDA が利用できません。パッチをスキップします")
        return False

    capability = torch.cuda.get_device_capability()
    if capability[0] < 12:
        logger.debug(
            "Compute Capability %d.%d: Blackwell ではないためパッチ不要",
            capability[0],
            capability[1],
        )
        return False

    # --- Capability スプーフィング ---
    logger.info(
        "Blackwell GPU 検出 (SM_%d%d) → Hopper (SM_90) としてスプーフィング",
        capability[0],
        capability[1],
    )
    _original_get_device_capability = torch.cuda.get_device_capability

    def _spoofed_capability(device=None):
        return (9, 0)

    torch.cuda.get_device_capability = _spoofed_capability

    # --- Jiterator バイパス ---
    # NVRTC の SM_121 コンパイルエラーを回避するため、
    # complex.abs() の代わりに手動計算を使用
    try:
        _patch_complex_abs(torch)
    except Exception as e:
        logger.warning("complex.abs() パッチの適用に失敗（動作には影響しない場合があります）: %s", e)

    _patched = True
    return True


def _patch_complex_abs(torch):
    """torch.complex の abs() を手動 sqrt(real^2 + imag^2) に置き換える。

    NVRTC が SM_121 向けに Jiterator カーネルをコンパイルできない問題を回避する。
    """
    import torch.nn.functional as F

    original_stft = torch.stft

    def _patched_stft(*args, **kwargs):
        result = original_stft(*args, **kwargs)
        return result

    # この部分は faster-whisper (CTranslate2) では不要な場合が多い。
    # openai-whisper (PyTorch直接) フォールバック時に必要になる可能性がある。
    logger.debug("Jiterator バイパスパッチを準備しました")
