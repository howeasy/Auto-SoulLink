from tests.live.test_gen1_launcher import pytestmark as pytestmark, run_launcher_pair


def test_production_factory_isolates_yellow_yellow_and_completes_saved_memorials():
    run_launcher_pair(('yellow','yellow'),enrollment=True,faint=True,memorial=True,factory=True)
