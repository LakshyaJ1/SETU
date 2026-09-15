# SETU speed-model training

For new Android recordings, use the [phone collection pipeline](../docs/22-phone-training-pipeline.md)
and `finetune_phone.py`. It consumes verified, explicitly split 400×6 datasets,
requires an existing checkpoint, and writes a research candidate without changing
the Android assets. Do not mix its GPS-reference metrics with the wheel-speed
metrics of the historical IO-VNBD run below.

Phone dataset conversion defaults to Car. Pass `--vehicle Two-wheeler` to
`python -m setu.collection` to target a separate scooter research candidate, preserving
activity/mount provenance and all quality/split gates. The selected scooter rides
remain diagnostic-only; no new weights were trained or promoted from them. See
the [scooter data review](../docs/24-scooter-data-review.md).

The final `speed_int8.tflite` uses dynamic-range int8 weights with float activations and preprocessing. Export freezes trained variables to constants to avoid unresolved runtime variables. It passes the notebook's parity thresholds, while its mean error exceeds the stricter project target; the float reference is also included. The uncertainty coverage gate remains unmet, so neither export is approved for navigation.

The final run changes batch-normalization momentum from 0.99 to 0.9. A checkpoint audit confirmed that the original running statistics retained enough initial variance to collapse inference to nearly constant speed, despite variable predictions in training mode. The original trained checkpoint is retained in `baseline-v3.zip`. Export uses an uncompiled model clone to avoid deserializing the training-only loss closure.

The original `setu_speed_model.ipynb` is preserved. The runnable training copy is `setu_speed_model_training.ipynb`; its Python equivalent is `kaggle_train.py`. Run `python prepare_training.py` to rebuild both from the original model definitions and the repaired ingestion/training modules.

This run uses real synchronized IO-VNBD phone IMU and vehicle wheel-speed records from repository commit `118939602e3422d47b8ab0807b623751c3ac135b`. Each downloaded CSV is checked against its Git LFS SHA-256 and byte count. There is no synthetic training fallback. The synthetic generator is retained only for the original notebook's diagnostic probes.

The loader matches V/S filenames case-insensitively across their separate directories, reads the actual accelerometer columns, and converts wheel angular speed to linear speed using a per-run rolling radius. Phone elapsed-time counters reset in several recordings, so it uses the continuous date/time column for interpolation. It preserves the publisher's synchronized row correspondence, verifies it against the paired GPS positions, rejects unequal-length pairs, and excludes windows crossing either logger's gaps or duplicate timestamps. Radius fitting uses reliable, steady GPS epochs only to construct wheel-speed labels; the network receives six IMU channels and no GPS or CAN values. The exact accepted/rejected runs and calibration details are recorded in the bundle.

Accepted driver E recordings provide training runs. Driver B (M) provides separate validation and uncertainty-calibration blocks with a ten-second guard band. Accepted driver A recordings are reserved for the final test. Driver D's Y1 pair failed the GPS alignment cross-check (median separation approximately 652 m), so it is excluded. This split was set before optimization or model evaluation. It measures transfer to one held-out driver in the same vehicle/country, not transfer to other countries, vehicles, phones, or two-wheelers.

The CNN-GRU and Gaussian-NLL/Huber/turn-regularization loss come from the original notebook. The EMA gravity feature is initialized correctly from the first sample, the custom layer is registered for serialization, and softplus uses a serializable activation name. The window remains 400 samples over four seconds at a 100 Hz internal grid. The real source is approximately 10 Hz; interpolation cannot restore missing high-frequency information. The hop is one second to limit redundant overlapping examples and memory use.

Training allows 40 epochs, saves the lowest-validation-loss checkpoint, reduces the learning rate on a plateau, and stops early after nine epochs without improvement. Calibration uses its separate block. The final report includes a constant training-median baseline and explicit deployment limitations. The inference-only GRU clone is unrolled for TFLite conversion while retaining the learned weights. The quantized export contains mixed integer/float operations and float32 input/output; its error is measured rather than assumed negligible.

The private training run is https://www.kaggle.com/code/psychoxd12/setu-speed-real-training-20260914. Completed artifacts belong in `setu-speed-v1/`, with a convenience ZIP alongside it. `speed_model.keras` and `best.weights.h5` preserve the trained model even if TFLite export fails. `environment-freeze.txt`, data hashes, split metadata, calibration, history, and evaluation support reproduction. `verification_windows.npz` contains public-dataset test samples for local replay.

After downloading, run `python verify_bundle.py` from this folder to check every manifest hash, recalculate the reported held-out errors, reload the Keras checkpoint, and replay both TFLite models against saved Kaggle outputs. The local verification report is kept outside the bundle so its original manifest remains unchanged.

All local edits and outputs are confined to this `notebooks` directory. No app code, shared Python installation, live endpoint, or model deployment is modified. Training completion does not establish phone latency or navigation readiness; inspect `eval_report.json` before using the result.
