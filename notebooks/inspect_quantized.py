import pathlib
import numpy as np
import setu_model as sm

root = pathlib.Path(__file__).resolve().parent / "setu-speed-v1"
x = np.load(root/"verification_windows.npz")["imu"]
for delegates in (True, False):
    options = {} if delegates else {"experimental_op_resolver_type": sm.tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES}
    interpreter = sm.tf.lite.Interpreter(model_path=str(root/"speed_int8.tflite"), num_threads=1, **options)
    interpreter.allocate_tensors()
    inp, output = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    bad = []
    for i, sample in enumerate(x):
        interpreter.set_tensor(inp["index"], sample[None])
        interpreter.invoke()
        if not np.all(np.isfinite(interpreter.get_tensor(output["index"]))):
            bad.append(i)
            if len(bad) == 5:
                break
    print("XNNPACK", delegates, "nonfinite_examples", bad, flush=True)
