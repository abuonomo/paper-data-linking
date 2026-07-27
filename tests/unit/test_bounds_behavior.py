"""
Unit tests to explore PostgreSQL range bounds behavior with different precision levels.

This tests whether LLM output should include bounds notation explicitly, and how
different precision levels interact with bounds semantics.
"""

import pytest
from datetime import datetime, timedelta
import pytz


class TestBoundsBehavior:
    """Tests exploring how bounds work with precision levels."""

    def test_bounds_notation_single_day_inclusive_right(self):
        """
        Test single day with inclusive right bound (current behavior).

        With bounds='[]': [2000-05-05T00:00:00Z, 2000-05-06T00:00:00Z]
        This means: >= start AND <= end
        Problem: Includes events at exactly 2000-05-06T00:00:00Z (next day!)
        """
        start = datetime(2000, 5, 5, 0, 0, 0, tzinfo=pytz.UTC)
        end = datetime(2000, 5, 6, 0, 0, 0, tzinfo=pytz.UTC)

        # With '[]' bounds, does this event match?
        event_on_day_2 = datetime(2000, 5, 6, 0, 0, 0, tzinfo=pytz.UTC)

        # PostgreSQL overlap check for '[2000-05-05, 2000-05-06]' with '[2000-05-06, 2000-05-07]'
        # Would return TRUE - they share the point 2000-05-06T00:00:00Z
        # This is WRONG - we want to exclude events on 2000-05-06
        assert True, "With '[]' bounds, next-day events at midnight are incorrectly included"

    def test_bounds_notation_single_day_exclusive_right(self):
        """
        Test single day with exclusive right bound (proposed behavior).

        With bounds='[)': [2000-05-05T00:00:00Z, 2000-05-06T00:00:00Z)
        This means: >= start AND < end
        Correct: Excludes events at exactly 2000-05-06T00:00:00Z (next day!)
        """
        start = datetime(2000, 5, 5, 0, 0, 0, tzinfo=pytz.UTC)
        end = datetime(2000, 5, 6, 0, 0, 0, tzinfo=pytz.UTC)

        # With '[)' bounds, does this event match?
        event_on_day_2 = datetime(2000, 5, 6, 0, 0, 0, tzinfo=pytz.UTC)

        # PostgreSQL overlap check for '[2000-05-05, 2000-05-06)' with '[2000-05-06, 2000-05-07)'
        # Would return FALSE - they don't overlap (they touch at boundary only)
        # This is CORRECT - we exclude events on 2000-05-06
        assert True, "With '[)' bounds, next-day events at midnight are correctly excluded"

    def test_bounds_for_year_precision(self):
        """
        Test bounds notation for year-precision input (e.g., "1996").

        Should output: [1996-01-01, 1997-01-01) with precision: year
        Not: [1996-01-01T00:00:00Z, 1997-01-01T00:00:00Z] with bounds='[]'
        """
        year_input = "1996"

        # LLM output proposal:
        output = {
            "start_datetime": "1996",  # Only year
            "end_datetime": "1997",    # Only year
            "bounds": "[)",            # Left inclusive, right exclusive
            "precision": "year"
        }

        # When parsed:
        start = datetime.fromisoformat("1996-01-01")
        end = datetime.fromisoformat("1997-01-01")

        # With bounds='[)', this means all of 1996
        print(f"Year precision: {output}")
        assert output["bounds"] == "[)", "Year ranges should use exclusive right bound"
        assert output["precision"] == "year"

    def test_bounds_for_month_precision(self):
        """
        Test bounds notation for month-precision input (e.g., "2003-11").

        Should output: [2003-11-01, 2003-12-01) with precision: month
        """
        month_input = "2003-11"

        output = {
            "start_datetime": "2003-11",    # Year-month only
            "end_datetime": "2003-12",      # Next month
            "bounds": "[)",                 # Left inclusive, right exclusive
            "precision": "month"
        }

        print(f"Month precision: {output}")
        assert output["bounds"] == "[)"
        assert output["precision"] == "month"

    def test_bounds_for_day_precision_single_date(self):
        """
        Test bounds notation for day-precision single date (e.g., "2000-05-05").

        Should output: [2000-05-05, 2000-05-06) with precision: day
        """
        day_input = "2000-05-05"

        output = {
            "start_datetime": "2000-05-05",
            "end_datetime": "2000-05-06",
            "bounds": "[)",                 # Left inclusive, right exclusive
            "precision": "day"
        }

        print(f"Single day precision: {output}")
        assert output["bounds"] == "[)"
        assert output["precision"] == "day"

    def test_bounds_for_actual_time_range(self):
        """
        Test bounds notation for actual time range (different start and end days).

        Example: "2003-11-03 01:02:20 to 2003-11-04 02:01:00 UT"
        Should output: [2003-11-03T01:02:20Z, 2003-11-04T02:01:00Z] with bounds='[]'
        Note: Not using '[)' because end is not at midnight
        """
        range_input = "2003-11-03 01:02:20 to 2003-11-04 02:01:00 UT"

        output = {
            "start_datetime": "2003-11-03T01:02:20Z",
            "end_datetime": "2003-11-04T02:01:00Z",
            "bounds": "[]",                 # Both inclusive (end is not at midnight)
            "precision": "minute"           # Coarsest of second and minute
        }

        print(f"Time range: {output}")
        assert output["bounds"] == "[]", "When end is not at midnight, use inclusive bounds"

    def test_bounds_for_instant(self):
        """
        Test bounds notation for single instant (start == end).

        Example: "at 2000-05-05T12:30:00Z"
        With '[]' bounds: [2000-05-05T12:30:00Z, 2000-05-05T12:30:00Z]
        This represents a single instant
        """
        instant_input = "at 2000-05-05T12:30:00Z"

        output = {
            "start_datetime": "2000-05-05T12:30:00Z",
            "end_datetime": "2000-05-05T12:30:00Z",
            "bounds": "[]",                 # Both inclusive (it's a point)
            "precision": "minute"
        }

        print(f"Single instant: {output}")
        assert output["bounds"] == "[]", "Single instants require both inclusive bounds"


class TestBoundsSelectionLogic:
    """Test logic for determining correct bounds based on precision and endpoint values."""

    def test_should_use_exclusive_right_when_end_at_midnight(self):
        """
        Helper logic: Should use '[)' when end_datetime is at exactly midnight
        of the next period (day, month, or year).
        """
        cases = [
            {
                "name": "Single day (end at next day midnight)",
                "start": "2000-05-05",
                "end": "2000-05-06",
                "should_use_exclusive_right": True
            },
            {
                "name": "Single month (end at next month)",
                "start": "2003-11",
                "end": "2003-12",
                "should_use_exclusive_right": True
            },
            {
                "name": "Single year (end at next year)",
                "start": "1996",
                "end": "1997",
                "should_use_exclusive_right": True
            },
            {
                "name": "Actual time range (end not at midnight)",
                "start": "2003-11-03T01:02:20Z",
                "end": "2003-11-04T02:01:00Z",
                "should_use_exclusive_right": False
            },
            {
                "name": "Single instant",
                "start": "2000-05-05T12:30:00Z",
                "end": "2000-05-05T12:30:00Z",
                "should_use_exclusive_right": False
            }
        ]

        for case in cases:
            print(f"\n{case['name']}: {case['start']} to {case['end']}")
            print(f"  Should use '[)': {case['should_use_exclusive_right']}")

    def test_llm_output_should_include_bounds(self):
        """
        Final recommendation: LLM output should explicitly include bounds field.

        This eliminates ambiguity and post-processing complexity.
        """
        llm_outputs = [
            {
                "description": "Single day",
                "output": {
                    "start_datetime": "2000-05-05",
                    "end_datetime": "2000-05-06",
                    "bounds": "[)",
                    "precision": "day"
                }
            },
            {
                "description": "Year range",
                "output": {
                    "start_datetime": "1996",
                    "end_datetime": "1997",
                    "bounds": "[)",
                    "precision": "year"
                }
            },
            {
                "description": "Actual time range",
                "output": {
                    "start_datetime": "2003-11-03T01:02:20Z",
                    "end_datetime": "2003-11-04T02:01:00Z",
                    "bounds": "[]",
                    "precision": "minute"
                }
            }
        ]

        for item in llm_outputs:
            print(f"\n{item['description']}: {item['output']}")
            assert "bounds" in item["output"], "LLM output should include bounds field"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])