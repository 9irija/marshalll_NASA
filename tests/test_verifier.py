"""The verifier is the code-level guarantee that no safety-critical number is invented."""
from flight_controller import verifier
from flight_controller.retrieval import BM25

TOOLS = [{"routes": [{"o2_kg": 0.2113, "distance_m": 6507.1, "duration_s": 10059.2, "batt_wh": 279.42,
                      "max_slope_deg": 14.87, "point_of_no_return": {"lat": 18.45074, "lon": 77.40144, "t_min": 63.2}}]}]


def test_accepts_numbers_copied_or_rounded_from_tools():
    ans = ("Safest: 6.51 km, 2.79 hours, O2 used 0.211 kg, battery 279 Wh, max slope 14.9 deg. "
           "Point of no return at T+63 minutes near 18.4507 N 77.4014 E.")
    r = verifier.check(ans, TOOLS)
    assert r["passed"], r["unverified"]
    assert len(r["verified"]) >= 7


def test_unit_conversion_grams_and_metres():
    assert verifier.check("about 211 g of oxygen over 6507 m", TOOLS)["passed"]


def test_rejects_invented_numbers():
    r = verifier.check("You will need about 0.35 kg O2 and 3.5 hours.", TOOLS)
    assert not r["passed"]
    assert {u["text"] for u in r["unverified"]} == {"0.35 kg", "3.5 hours"}


def test_rejects_llm_arithmetic():
    # 0.6 - 0.2113 = 0.3887 is NOT in the tool output: computing it is the model's job we forbid
    assert not verifier.check("You will have 0.389 kg left.", TOOLS)["passed"]


def test_unitless_numbers_not_checked():
    assert verifier.check("Perseverance took a core on sol 558 [1]; 3 stops planned.", TOOLS)["passed"]


def test_document_numbers_accepted_only_if_quoted_from_passage():
    tools = TOOLS + [{"passages": [{"n": 1, "text": "mean metabolic rate of 1210 BTU/hr over 3.5 hours"}]}]
    assert verifier.check("Apollo crews averaged about 3.5 hours per EVA [1].", tools)["passed"]


def test_bm25_ranks_relevant_chunk_first():
    docs = [{"source_id": "a", "title": "Suits", "text": "portable life support system oxygen tank pressure"},
            {"source_id": "b", "title": "Geology", "text": "olivine carbonate delta jezero crater"},
            {"source_id": "c", "title": "Walkback", "text": "walkback limit distance to the lunar module oxygen"}]
    hits = BM25(docs).search("walkback limit oxygen", 2)
    assert hits[0][1]["source_id"] == "c"


def test_radiation_dose_is_checked():
    from flight_controller.verifier import check

    tool = [{"radiation": {"gcr_dose_msv": 0.0745, "max_time_to_shelter_min": 66.9}}]
    assert check("Cosmic-ray dose on this walk is 0.075 mSv.", tool)["passed"]
    assert check("Cosmic-ray dose on this walk is 75 µSv.", tool)["passed"]
    bad = check("Cosmic-ray dose on this walk is 0.3 mSv.", tool)
    assert not bad["passed"] and bad["unverified"][0]["dim"] == "dose"
