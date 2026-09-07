import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from setu.core import so3
from setu.estimation.riekf import InvariantEkf

ROOT = Path(__file__).resolve().parents[1]


def snapshot(engine):
    state = engine.s
    return np.concatenate(
        (
            state.X.R.ravel(),
            state.X.v,
            state.X.p,
            state.b_g,
            state.b_a,
            [state.k_svo, state.t],
            state.P.ravel(),
        )
    ).tolist()


def make_case(name, moving):
    rotation = so3.from_euler_rpy(0.2, -0.1, 0.5) if moving else np.eye(3)
    position = np.array([5.0, -2.0, 1.0]) if moving else np.zeros(3)
    velocity = np.array([8.0, 1.0, 0.2]) if moving else np.zeros(3)
    engine = InvariantEkf.initialise(position.copy(), velocity.copy(), rotation.copy())
    actions = []
    for step in range(120):
        seconds = (0.005, 0.01, 0.0075)[step % 3]
        accel = (
            np.array([0.4 * np.sin(step / 7), 0.15 * np.cos(step / 11), 9.80665])
            if moving
            else np.array([0.0, 0.0, 9.80665])
        )
        gyro = np.array([0.01, -0.005, 0.08 * np.cos(step / 13)]) if moving else np.zeros(3)
        noise_scale = 1.0 + step % 4
        engine.propagate(accel, gyro, seconds, noise_scale)
        action = dict(
            kind="imu",
            acceleration=accel.tolist(),
            angularRate=gyro.tolist(),
            seconds=seconds,
            noiseScale=noise_scale,
        )
        if step % 20 == 19:
            action["expected"] = snapshot(engine)
        actions.append(action)
        if not moving or step % 20 != 19:
            continue
        measurements = [
            (
                "POSITION",
                "update_position",
                (engine.s.position + [0.2, -0.1, 0.05]).tolist(),
                [1.0, 1.0, 2.0],
            ),
            (
                "VELOCITY",
                "update_velocity",
                (engine.s.velocity + [0.05, -0.02, 0.01]).tolist(),
                [0.2, 0.3, 0.5],
            ),
            ("FORWARD_SPEED", "update_forward_speed", [engine.s.body_speed + 0.03], [0.3]),
            ("NHC", "update_nhc", [0.0, 0.0], [0.08, 0.08]),
            ("ZUPT", "update_zupt", [0.0, 0.0, 0.0], [0.02, 0.02, 0.02]),
            (
                "SVO_FREQUENCY",
                "update_svo_frequency",
                [engine.s.body_speed / engine.s.k_svo + 0.02],
                [0.2],
            ),
            (
                "POSITION_2D",
                "update_position_2d",
                (engine.s.position[:2] + [0.1, -0.1]).tolist(),
                [2.0, 2.0],
            ),
            ("ALTITUDE", "update_altitude", [float(engine.s.position[2] + 0.1)], [1.0]),
            ("POSITION", "update_position", [100000.0, 100000.0, 100000.0], [1.0, 1.0, 1.0]),
        ]
        for kind, method, values, deviations in measurements:
            update = getattr(engine, method)
            if kind in ("NHC", "ZUPT"):
                result = update(deviations[0])
            elif len(values) == 1:
                result = update(values[0], deviations[0])
            else:
                result = update(np.array(values), np.array(deviations))
            actions.append(
                dict(
                    kind=kind,
                    values=values,
                    deviations=deviations,
                    accepted=result.accepted,
                    nis=result.nis,
                    expected=snapshot(engine),
                )
            )
    return dict(
        name=name,
        rotation=rotation.ravel().tolist(),
        position=position.tolist(),
        velocity=velocity.tolist(),
        actions=actions,
        expected=snapshot(engine),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    sources = [
        "setu/estimation/riekf.py",
        "setu/core/so3.py",
        "setu/core/se23.py",
        "setu/core/constants.py",
    ]
    payload = dict(
        version=1,
        sources={path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources},
        cases=[make_case("stationary", False), make_case("all-measurement-channels", True)],
    )
    output = ROOT / "android/app/src/androidTest/assets/native-filter-parity.json"
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n"
    if options.check:
        if output.read_text(encoding="utf-8") != encoded:
            raise SystemExit(
                "Native fixture differs from the Python reference; "
                "regenerate and rerun device parity checks."
            )
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8", newline="\n")
    action_count = sum(len(case["actions"]) for case in payload["cases"])
    print(f"Native parity fixture: {len(payload['cases'])} cases, {action_count} actions.")


if __name__ == "__main__":
    main()
