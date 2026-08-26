# LoRA SFT v2 failure log

## 2026-08-25: answer truncated from long JD

The first r=4 run produced intermittent NaN losses and a NaN validation loss. Root cause: the old encoder
concatenated a long prompt and answer, then applied right truncation to 512 tokens. For long public JDs the answer
was removed completely, leaving every label at `-100`.

Resolution: prompt and response are tokenized separately; up to half of the sequence window is reserved for the
target response, and training now fails fast on non-finite loss. The invalid run is retained in the server log but
excluded from model comparison. All ranks restart from the same base checkpoint after this correction.
