# Silent FX chip bank

`silent_keysounds.s3p` contains fifteen identical samples of 250 ms of silence,
encoded as stereo 44.1 kHz WMA Professional. Packages copy it as `general_sampler_<slot>.s3p`
when rendered FX chips need a silent native sample.

Regenerate from the repository root on Windows:

```sh
uv run python scripts/generate_silent_sampler.py
```

Generation requires the Windows Media Format runtime. Copying the bundled bank
requires no encoder.
