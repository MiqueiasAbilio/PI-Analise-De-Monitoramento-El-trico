import unittest
from datetime import datetime

from app import DEFAULT_SETTINGS, allocate_energy, analyze


class EnergyAllocationTests(unittest.TestCase):
    def test_full_day_uses_configured_profile_and_preserves_energy(self):
        start = datetime(2026, 3, 10)
        end = datetime(2026, 3, 11)

        result = allocate_energy(start, end, 24, DEFAULT_SETTINGS, start, end)

        self.assertAlmostEqual(result["manha"], 4.8)
        self.assertAlmostEqual(result["tarde"], 7.2)
        self.assertAlmostEqual(result["noite"], 12)
        self.assertAlmostEqual(sum(result.values()), 24)

    def test_partial_date_filter_allocates_only_overlapping_energy(self):
        start = datetime(2026, 3, 10)
        end = datetime(2026, 3, 12)
        day_start = datetime(2026, 3, 11)
        day_end = datetime(2026, 3, 12)

        result = allocate_energy(start, end, 48, DEFAULT_SETTINGS, day_start, day_end)

        self.assertAlmostEqual(sum(result.values()), 24)

    def test_zero_share_does_not_discard_reading_within_that_period(self):
        settings = {"manha": "0", "tarde": "100", "noite": "0", "tarifa": "0.95"}
        start = datetime(2026, 3, 10, 1)
        end = datetime(2026, 3, 10, 8)

        result = allocate_energy(start, end, 8, settings, start, end)

        self.assertAlmostEqual(sum(result.values()), 8)
        self.assertAlmostEqual(result["noite"], 8 * 5 / 7)
        self.assertAlmostEqual(result["manha"], 8 * 2 / 7)

    def test_analysis_calculates_cost_and_weekly_projection(self):
        start = datetime(2026, 3, 10)
        end = datetime(2026, 3, 11)
        readings = [{"start_at": start.isoformat(), "end_at": end.isoformat(), "kwh": 24}]

        result = analyze(readings, start, end, DEFAULT_SETTINGS)

        self.assertAlmostEqual(result["total_cost"], 22.8)
        self.assertAlmostEqual(result["weekly_kwh"], 168)
        self.assertAlmostEqual(result["periods"]["noite"]["cost"], 11.4)


if __name__ == "__main__":
    unittest.main()
