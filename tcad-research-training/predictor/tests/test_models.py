"""Small synthetic numeric checks, never a scientific performance benchmark."""

import copy
import io
import json
import math
import unittest

import numpy as np
import torch

from dram_predictor.data import DataError
from dram_predictor.features import Encoder, record, source_off_record
from dram_predictor.losses import (
    masked_bce,
    masked_huber,
    poisson_count_loss,
    proxy_cross_section_loss,
)
from dram_predictor.mechanism import MechanismCalibrator, rectangular_response
from dram_predictor.models import CrossSectionNet, ResponseNet


def calibration_fixture():
    x = np.array([[d, s] for d in (-1.0, 0.0, 1.0) for s in (0.0, 1.0)])
    controls, responses = [], []
    t = np.array([0.0, 0.25, 0.5, 1.0, 2.0, 4.0])
    rt = np.array([-0.5, 0.0, 0.25, 0.5, 1.0, 2.0, 4.0])
    for i, row in enumerate(x):
        tau = np.exp(math.log(2.0) + 0.1 * row[0] + 0.2 * row[1])
        gain = -0.7 + 1.4 * row[1] + 0.1 * row[0]
        common = {
            "profile_id": f"synthetic-profile-{i // 2}",
            "state": int(row[1]),
            "capacitance_fF": 20.0,
            "mechanism_validated": True,
            "source_hash": f"synthetic-only-{i}",
        }
        controls.append({
            **common, "control_id": f"c{i}", "time_ns": t.tolist(),
            "reference_voltage_V": 0.2, "voltage_V": (0.2 + np.exp(-t / tau)).tolist(),
        })
        responses.append({
            **common, "response_id": f"r{i}", "time_ns": rt.tolist(),
            "generated_charge_fC": 4.0, "source_duration_ns": 0.25,
            "delta_voltage_V": (gain * 4 / 20 * rectangular_response(rt, 0.25, tau)).tolist(),
        })
    return x, controls, responses


class MechanismTests(unittest.TestCase):
    def test_rectangular_kernel_analytic_and_impulse_limit(self):
        t = np.array([-1.0, 0.0, 0.5, 1.0, 2.0, 4.0])
        actual = rectangular_response(t, 1.0, 2.0)
        expected = np.where(
            t < 0, 0.0,
            2 * (1 - np.exp(-np.minimum(np.maximum(t, 0), 1) / 2))
            * np.exp(-np.maximum(t - 1, 0) / 2),
        )
        np.testing.assert_allclose(actual, expected, atol=1e-14)
        np.testing.assert_allclose(
            rectangular_response(t[t > 0], 1e-13, 2.0),
            rectangular_response(t[t > 0], 0.0, 2.0),
            atol=1e-12,
        )
        self.assertEqual(float(rectangular_response(-0.1, 0, 2)), 0)

    def test_invalid_physical_times_rejected(self):
        for duration, tau in [(-1, 2), (1, 0), (1, float("nan"))]:
            with self.assertRaises(ValueError):
                rectangular_response([0, 1], duration, tau)

    def test_shared_calibration_recovers_signed_gain_and_positive_tau(self):
        x, controls, responses = calibration_fixture()
        model = MechanismCalibrator(ridge=1e-10).fit(x, controls, x, responses)
        pred = model.predict(x)
        np.testing.assert_allclose(
            pred["tau_ns"], np.exp(math.log(2) + 0.1 * x[:, 0] + 0.2 * x[:, 1]),
            rtol=1e-7,
        )
        np.testing.assert_allclose(pred["gain"], -0.7 + 1.4 * x[:, 1] + 0.1 * x[:, 0], atol=1e-7)
        self.assertTrue(np.any(pred["gain"] < 0))
        self.assertEqual(model.control_source_ids, [f"c{i}" for i in range(6)])
        self.assertEqual(model.response_source_ids, [f"r{i}" for i in range(6)])

    def test_serialization_and_profile_rename_do_not_change_predictions(self):
        x, controls, responses = calibration_fixture()
        original = MechanismCalibrator().fit(x, controls, x, responses)
        payload = json.loads(json.dumps(original.to_dict(), allow_nan=False))
        restored = MechanismCalibrator.from_dict(payload)
        np.testing.assert_array_equal(original.predict(x)["tau_ns"], restored.predict(x)["tau_ns"])
        changed_c, changed_r = copy.deepcopy(controls), copy.deepcopy(responses)
        for row in changed_c + changed_r:
            row["profile_id"] = "unrelated-display-name"
        renamed = MechanismCalibrator().fit(x, changed_c, x, changed_r)
        np.testing.assert_array_equal(original.predict(x)["gain"], renamed.predict(x)["gain"])

    def test_skipped_sources_remain_in_provenance(self):
        x, controls, responses = calibration_fixture()
        controls[0]["mechanism_validated"] = False
        responses[0]["generated_charge_fC"] = 0
        model = MechanismCalibrator().fit(x, controls, x, responses)
        skipped = [r for r in model.to_dict()["calibration_records"] if r["status"] == "skipped"]
        self.assertEqual({r["id"] for r in skipped}, {"c0", "r0"})
        self.assertIn("c0", model.control_source_ids)
        self.assertIn("r0", model.response_source_ids)

    def test_no_controls_or_no_radiation_cannot_fabricate_calibration(self):
        x, controls, responses = calibration_fixture()
        for record in controls:
            record["voltage_V"] = [0.2] * len(record["time_ns"])
        with self.assertRaisesRegex(ValueError, "no identifiable training-side RC control"):
            MechanismCalibrator().fit(x, controls, x, responses)
        x, controls, responses = calibration_fixture()
        for record in responses:
            record["generated_charge_fC"] = 0
        model = MechanismCalibrator()
        with self.assertRaisesRegex(ValueError, "no identifiable training-side radiation"):
            model.fit(x, controls, x, responses)
        with self.assertRaises(ValueError):
            model.to_dict()


class NetworkTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(1729)
        torch.set_num_threads(1)
        self.x = torch.randn(3, 5)
        self.off = torch.zeros_like(self.x)
        self.args = {
            "time_ns": torch.tensor([-1.0, 0.0, 0.25, 1.0, 3.0]),
            "capacitance_fF": torch.full((3,), 20.0),
            "tau_ns": torch.full((3,), 2.0),
            "gain": torch.tensor([-0.8, 0.7, 3.0]),
            "generated_charge_fC": torch.full((3,), 4.0),
            "source_duration_ns": torch.full((3,), 0.25),
        }

    def test_hybrid_causality_zero_source_and_capacitor_identity(self):
        model = ResponseNet(5, window_ns=3.0)
        pred = model(self.x, self.off, **self.args)
        torch.testing.assert_close(pred["delta_voltage_V"][:, 0], torch.zeros(3), rtol=0, atol=0)
        torch.testing.assert_close(
            pred["capacitor_charge_fC"],
            pred["delta_voltage_V"] * self.args["capacitance_fF"][:, None],
        )
        args = {**self.args, "generated_charge_fC": torch.zeros(3)}
        off = model(self.off, self.off, **args)
        torch.testing.assert_close(off["delta_voltage_V"], torch.zeros(3, 5), rtol=0, atol=0)
        torch.testing.assert_close(off["port_charge_fC"], torch.zeros(3), rtol=0, atol=0)

    def test_hybrid_has_finite_gradients(self):
        model = ResponseNet(5, hidden=(8, 8), window_ns=3.0)
        prediction = model(self.x, self.off, **self.args)
        loss = prediction["delta_voltage_V"].square().mean() + prediction["port_charge_fC"].square().mean()
        loss.backward()
        self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters()))

    def test_collection_head_has_no_generation_charge_ceiling(self):
        model = ResponseNet(1, hidden=(1,), window_ns=3.0)
        with torch.no_grad():
            for p in model.parameters():
                p.zero_()
            model.network[0].weight.fill_(1)
            model.network[-1].weight[model.residual_bins, 0] = 10
        pred = model(
            torch.tensor([[10.0]]), torch.tensor([[0.0]]),
            time_ns=torch.tensor([0.0, 1.0, 3.0]),
            capacitance_fF=torch.tensor([20.0]), tau_ns=torch.tensor([2.0]),
            gain=torch.tensor([0.5]), generated_charge_fC=torch.tensor([1.0]),
            source_duration_ns=torch.tensor([0.25]),
        )
        self.assertGreater(float(pred["port_charge_fC"][0].detach()), 1.0)
        self.assertNotEqual(float(pred["port_charge_fC"][0].detach()), float(pred["capacitor_charge_fC"][0, -1].detach()))

    def test_mechanism_only_has_no_invented_readout_heads(self):
        model = ResponseNet(5, mode="mechanism_only")
        pred = model(self.x, self.off, **self.args)
        self.assertFalse(model.trainable_auxiliary)
        self.assertEqual(len(list(model.parameters())), 0)
        self.assertTrue(torch.isfinite(pred["delta_voltage_V"]).all())
        for head in ("port_charge_fC", "margin_V", "upset_logit"):
            self.assertTrue(torch.isnan(pred[head]).all())

    def test_plain_waveform_does_not_use_tau_or_gain(self):
        model = ResponseNet(5, mode="plain", window_ns=3.0)
        first = model(self.x, self.off, **self.args)
        second = model(
            self.x, self.off, **{**self.args, "tau_ns": torch.full((3,), 500.0), "gain": torch.ones(3) * 50}
        )
        torch.testing.assert_close(first["delta_voltage_V"], second["delta_voltage_V"], rtol=0, atol=0)

    def test_frozen_window_does_not_change_with_later_prediction_grid(self):
        model = ResponseNet(5)
        first = model(self.x, self.off, **self.args)
        second = model(
            self.x, self.off, **{**self.args, "time_ns": torch.tensor([-1.0, 0.0, 0.25, 1.0, 3.0, 8.0])}
        )
        self.assertEqual(float(model.response_window_ns), 3.0)
        torch.testing.assert_close(first["delta_voltage_V"], second["delta_voltage_V"][:, :5])
        packed = io.BytesIO()
        torch.save(model.state_dict(), packed)
        packed.seek(0)
        restored = ResponseNet(5)
        restored.load_state_dict(torch.load(packed, weights_only=True))
        self.assertEqual(float(restored.response_window_ns), 3.0)
        torch.testing.assert_close(
            first["delta_voltage_V"], restored(self.x, self.off, **self.args)["delta_voltage_V"]
        )

    def test_cross_section_two_positive_heads_and_roundtrip(self):
        model = CrossSectionNet(5)
        pred = model(self.x)
        self.assertEqual(tuple(pred.shape), (3, 2))
        self.assertTrue(torch.all(pred > 0))
        self.assertTrue(torch.isfinite(pred).all())
        another = CrossSectionNet(5)
        another.load_state_dict(model.state_dict())
        torch.testing.assert_close(pred, another(self.x), rtol=0, atol=0)


class LossTests(unittest.TestCase):
    def test_masked_nan_never_poison_huber_gradients(self):
        pred = torch.tensor([1.0, float("nan")], requires_grad=True)
        loss = masked_huber(pred, [0.0, float("nan")], [True, False])
        self.assertEqual(float(loss.detach()), 0.5)
        loss.backward()
        torch.testing.assert_close(pred.grad, torch.tensor([1.0, 0.0]))

    def test_empty_masks_are_differentiable_zero(self):
        for fn in (
            lambda p: masked_huber(p, [float("nan")], [False]),
            lambda p: masked_bce(p, [float("nan")], [False]),
            lambda p: proxy_cross_section_loss(p, [float("nan")], [False], 1, [float("nan")]),
            lambda p: poisson_count_loss(p, [float("nan")], [float("nan")], [False]),
        ):
            pred = torch.tensor([float("nan")], requires_grad=True)
            loss = fn(pred)
            self.assertEqual(float(loss.detach()), 0.0)
            loss.backward()
            torch.testing.assert_close(pred.grad, torch.tensor([0.0]))

    def test_zero_counts_exact_and_positive_counts_without_pseudocount(self):
        sigma = torch.tensor([0.0, 0.25], requires_grad=True)
        loss = poisson_count_loss(sigma, [0.0, 0.0], [4.0, 4.0], [True, True])
        self.assertEqual(float(loss.detach()), 0.5)
        loss.backward()
        torch.testing.assert_close(sigma.grad, torch.tensor([2.0, 2.0]))
        actual = poisson_count_loss(torch.tensor([0.5]), [2.0], [4.0], [True])
        expected = 2 - 2 * math.log(2) + math.lgamma(3)
        self.assertAlmostEqual(float(actual.detach()), expected, places=6)

    def test_proxy_weights_are_capped_and_missing_weights_not_evaluated(self):
        pred = torch.tensor([2.0, 2.0, float("nan")], requires_grad=True)
        low = proxy_cross_section_loss(pred, [1.0, 0.0, float("nan")], [True, True, False], 1.0, [100.0, 1.0, float("nan")])
        high = proxy_cross_section_loss(pred, [1.0, 0.0, float("nan")], [True, True, False], 1.0, [1e20, 1.0, float("nan")])
        torch.testing.assert_close(low, high)
        low.backward()
        self.assertTrue(torch.isfinite(pred.grad).all())

    def test_uniform_proxy_confidence_scales_loss_and_gradient_by_one_quarter(self):
        pred = torch.tensor([2.0, 0.5, float("nan")], dtype=torch.float64, requires_grad=True)
        target, mask = [1.0, 0.0, float("nan")], [True, True, False]
        full = proxy_cross_section_loss(pred, target, mask, 1.0, [1.0, 1.0, float("nan")])
        quarter = proxy_cross_section_loss(pred, target, mask, 1.0, [0.25, 0.25, float("nan")])
        self.assertGreater(float(full.detach()), 0.0)
        torch.testing.assert_close(quarter, full * 0.25, rtol=0, atol=0)
        full_gradient = torch.autograd.grad(full, pred, retain_graph=True)[0]
        quarter_gradient = torch.autograd.grad(quarter, pred)[0]
        torch.testing.assert_close(quarter_gradient, full_gradient * 0.25, rtol=0, atol=0)
        self.assertEqual(float(quarter_gradient[-1]), 0.0)

    def test_unknown_is_not_a_binary_class_and_invalid_unmasked_rejected(self):
        with self.assertRaises(ValueError):
            masked_bce(torch.zeros(1), [0.5], [True])
        with self.assertRaises(ValueError):
            masked_huber(torch.zeros(1), [float("nan")], [True])
        with self.assertRaises(ValueError):
            poisson_count_loss(torch.ones(1), [0.5], [1.0], [True])


class FeatureRegressionTests(unittest.TestCase):
    @staticmethod
    def condition():
        return {
            "features": {
                "direction_x": 1.0, "direction_y": 0.0, "direction_z": 0.0,
                "capacitance_fF": 20.0, "gate_length_nm": 13.0,
                "incident_energy_MeV": 30.0,
            },
            "categories": {"structure_family": "synthetic", "particle": "proton"},
        }

    def test_explicit_direction_is_preserved_and_conflicting_angles_rejected(self):
        condition = self.condition()
        result = record(condition)
        self.assertEqual([result[k] for k in ("direction_x", "direction_y", "direction_z")],
                         [1.0, 0.0, 0.0])
        condition["features"].update(theta_deg=90.0, phi_deg=0.0)
        self.assertEqual(record(condition)["direction_x"], 1.0)
        condition["features"]["theta_deg"] = 0.0
        with self.assertRaisesRegex(DataError, "disagree"):
            record(condition)

    def test_complete_source_off_has_zero_response_despite_inactive_hit_metadata(self):
        condition = self.condition()
        primary = {
            "source_off": True,
            "source_features": {
                "generated_charge_fC": 0.0, "deposited_energy_MeV": 0.0,
                "source_duration_ns": 0.25, "hit_x_nm": 17.0, "hit_y_nm": 2.0,
                "secondary_count": 2.0,
            },
        }
        original = copy.deepcopy(primary)
        row = record(condition, primary, 0, {"x_nm": 0.0, "y_nm": 0.0, "z_nm": 0.0})
        off = source_off_record(row)
        encoder = Encoder("R").fit([row, off])
        x, x_off = (torch.from_numpy(encoder.transform([value])) for value in (row, off))
        self.assertTrue(torch.equal(x, x_off))
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(7)
            model = ResponseNet(encoder.width, hidden=(4, 4), window_ns=1.0)
            with torch.no_grad():
                prediction = model(
                    x, x_off, time_ns=torch.tensor([-0.1, 0.0, 0.2, 1.0]),
                    capacitance_fF=torch.tensor([20.0]), tau_ns=torch.tensor([2.0]),
                    gain=torch.tensor([0.7]), generated_charge_fC=torch.tensor([0.0]),
                    source_duration_ns=torch.tensor([0.25]),
                )
        for head in ("delta_voltage_V", "capacitor_charge_fC", "port_charge_fC"):
            torch.testing.assert_close(prediction[head], torch.zeros_like(prediction[head]),
                                       rtol=0, atol=0)
        self.assertEqual(primary, original)
        # Zero charge in a feature is not itself the complete-source-off flag.
        active = copy.deepcopy(primary)
        active["source_off"] = False
        self.assertEqual(record(condition, active)["source_duration_ns"], 0.25)
        self.assertEqual(record(condition, active)["hit_x_nm"], 17.0)


if __name__ == "__main__":
    unittest.main()
