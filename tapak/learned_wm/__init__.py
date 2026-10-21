"""Optional learned watermark for channel 2 (StegaStamp-style encoder-decoder).

STATUS: scaffold only. The correlation (spread-spectrum) decoder in
``tapak/decoder/ch_background.py`` is the production path and the fallback; it already
decodes the synthetic photo set at up to 30 degrees. The learned model would mainly help
with real phone pipelines (denoising, sharpening, moire) that the simulator does not
capture. PyTorch and onnxruntime are optional extras (``pip install -e .[learned]``) and
are never imported by the rest of TAPAK.

TODO (after the hackathon demo):
1. train ``model.TinyStegaStamp`` with ``train.py`` on rendered pages and the
   degradation simulator in ``degrade.py`` (blur, perspective, lighting, JPEG, crop);
2. export with ``export_onnx.py`` and run the decoder on CPU with onnxruntime;
3. feed its per-bit probabilities into ``decoder/fuse.py`` as another SoftBits source.
"""
