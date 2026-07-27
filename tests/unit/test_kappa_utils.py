"""Unit tests for kappa_utils — pure computation, no DB required."""
import pytest
from vso_query_builder.kappa_utils import fleiss_kappa, cohen_kappa_pair, interpret_kappa


class TestInterpretKappa:

    def test_almost_perfect(self):
        assert interpret_kappa(0.85) == 'Almost perfect'

    def test_substantial(self):
        assert interpret_kappa(0.70) == 'Substantial'

    def test_moderate(self):
        assert interpret_kappa(0.50) == 'Moderate'

    def test_fair(self):
        assert interpret_kappa(0.30) == 'Fair'

    def test_slight(self):
        assert interpret_kappa(0.10) == 'Slight'

    def test_poor(self):
        assert interpret_kappa(-0.05) == 'Poor'


class TestFleissKappa:

    def test_empty_input_returns_none_kappa(self):
        result = fleiss_kappa({})
        assert result['kappa'] is None
        assert result['n_items'] == 0

    def test_single_rater_insufficient(self):
        result = fleiss_kappa({'item1': ['approved']})
        assert result['kappa'] is None
        assert 'at least 2 raters' in result['interpretation']

    def test_perfect_agreement(self):
        # All raters agree on every item → kappa = 1.0
        data = {
            'item1': ['approved', 'approved'],
            'item2': ['rejected', 'rejected'],
            'item3': ['approved', 'approved'],
        }
        result = fleiss_kappa(data)
        assert result['kappa'] == pytest.approx(1.0, abs=1e-4)
        assert result['n_items'] == 3
        assert result['n_raters'] == 2

    def test_complete_disagreement(self):
        # Raters split evenly → kappa near 0 or negative
        data = {
            'item1': ['approved', 'rejected'],
            'item2': ['rejected', 'approved'],
        }
        result = fleiss_kappa(data)
        assert result['kappa'] is not None
        assert result['kappa'] <= 0.0

    def test_three_categories(self):
        data = {
            'a': ['approved', 'approved'],
            'b': ['rejected', 'rejected'],
            'c': ['needs_review', 'needs_review'],
        }
        result = fleiss_kappa(data)
        assert result['n_categories'] == 3
        assert result['kappa'] == pytest.approx(1.0, abs=1e-4)

    def test_explicit_categories(self):
        # Explicit categories list is honoured in the output even if some aren't used
        data = {
            'item1': ['approved', 'approved'],
            'item2': ['approved', 'approved'],
        }
        result = fleiss_kappa(
            data,
            categories=['approved', 'rejected', 'needs_review'],
        )
        assert result['categories'] == ['approved', 'rejected', 'needs_review']
        assert result['n_categories'] == 3
        assert result['kappa'] == pytest.approx(1.0, abs=1e-4)

    def test_returns_interpretation(self):
        data = {
            'i1': ['approved', 'approved'],
            'i2': ['approved', 'approved'],
        }
        result = fleiss_kappa(data)
        assert isinstance(result['interpretation'], str)
        assert len(result['interpretation']) > 0


class TestCohenKappaPair:

    def test_perfect_agreement(self):
        labels_a = ['approved', 'rejected', 'approved']
        labels_b = ['approved', 'rejected', 'approved']
        result = cohen_kappa_pair(labels_a, labels_b)
        assert result['kappa'] == pytest.approx(1.0, abs=1e-4)

    def test_complete_disagreement(self):
        labels_a = ['approved', 'approved']
        labels_b = ['rejected', 'rejected']
        result = cohen_kappa_pair(labels_a, labels_b)
        # p_observed = 0; kappa should be ≤ 0
        assert result['kappa'] <= 0.0

    def test_n_items(self):
        result = cohen_kappa_pair(['approved', 'rejected'], ['approved', 'approved'])
        assert result['n_items'] == 2

    def test_returns_interpretation(self):
        result = cohen_kappa_pair(['approved', 'approved'], ['approved', 'approved'])
        assert isinstance(result['interpretation'], str)

    def test_mismatched_lengths_raises(self):
        with pytest.raises(AssertionError):
            cohen_kappa_pair(['approved'], ['approved', 'rejected'])


@pytest.mark.django_db
class TestComputeKappaForValidations:
    """Integration-style tests using the DB."""

    def test_insufficient_data(self, dataset_usage_fixture):
        from vso_query_builder.models import DatasetUsageValidation
        from vso_query_builder.kappa_utils import compute_kappa_for_validations

        qs = DatasetUsageValidation.objects.none()
        result = compute_kappa_for_validations(qs)
        assert result['fleiss']['kappa'] is None
        assert result['n_total_validations'] == 0

    def test_two_raters_same_item(self, dataset_usage_fixture, db):
        from django.contrib.auth.models import User
        from vso_query_builder.models import DatasetUsageValidation
        from vso_query_builder.kappa_utils import compute_kappa_for_validations

        du = dataset_usage_fixture
        u1 = User.objects.create_user('kappa_u1', password='x')
        u2 = User.objects.create_user('kappa_u2', password='x')

        DatasetUsageValidation.objects.create(
            dataset_usage=du, user=u1, validation_status='approved'
        )
        DatasetUsageValidation.objects.create(
            dataset_usage=du, user=u2, validation_status='approved'
        )

        qs = DatasetUsageValidation.objects.filter(dataset_usage=du)
        result = compute_kappa_for_validations(qs)
        # Only 1 item with 2 raters → need ≥2 items for Fleiss
        assert result['n_total_validations'] == 2
        assert result['n_multi_rated_items'] == 1


@pytest.fixture
def dataset_usage_fixture(db, vso_datasource, observatory_factory, instrument_factory, paper_analysis_factory):
    from vso_query_builder.models import DatasetUsage
    from datetime import datetime
    from psycopg2.extras import DateTimeTZRange
    import pytz

    obs = observatory_factory("SDO_K")
    inst = instrument_factory(obs, "AIA_K")
    pa = paper_analysis_factory()
    start = datetime(2010, 1, 1, tzinfo=pytz.UTC)
    end = datetime(2010, 1, 2, tzinfo=pytz.UTC)
    return DatasetUsage.objects.create(
        paper=pa.paper,
        instrument=inst,
        paper_analysis=pa,
        observation_window=DateTimeTZRange(start, end, bounds="[]"),
        validation_status="pending",
    )
