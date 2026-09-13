# SETU training result

Training completed on a private Kaggle GPU using 19 real IO-VNBD recordings (7,471 windows). No synthetic data was used for training. Early stopping completed 13 epochs and selected epoch 4 by validation loss. The model contains 84,359 parameters.

The final test contains 15,902 windows from four recordings by held-out driver A. Mean absolute speed error is 2.9101 m/s (10.48 km/h), and RMSE is 3.9047 m/s. A constant training-median baseline has MAE 3.7460 m/s; the learned model changes MAE by +22.3% relative to that baseline (positive means improvement). Prediction standard deviation is 4.2565 m/s. Calibration was fitted on a separate block from driver B; test three-sigma coverage is 96.33%.

The model is saved in `setu-speed-v1/speed_model.keras`, with weights, calibration, split metadata, source-file hashes, and evaluation evidence. `setu-speed-v1.zip` contains the bundle. `local_verification.json` records local integrity and inference checks. `training_results.png` plots the recorded learning curve, predictions, and coverage; `evaluation_breakdown.json` gives per-run and speed-band errors.

The original notebook is preserved. Reproduction starts from `setu_speed_model_training.ipynb` or `kaggle_train.py`; see `TRAINING.md`. The private run is https://www.kaggle.com/code/psychoxd12/setu-speed-real-training-20260914.

These are research results on quality-filtered 10 Hz data from one vehicle/country. The rejected data and residual alignment limitations remain documented in `data_audit.json`. Phone latency, other vehicles, two-wheelers, and navigation accuracy have not been validated. Deployment approval remains false in the manifest.

TFLite float and mixed-int8 exports were produced. Quantized versus float speed error is 0.02605 m/s on average and 0.13091 m/s at worst. Notebook parity gate: True; stricter project parity gate: False.
