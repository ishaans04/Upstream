"""Code systems and clinical constants (GC-13).

Nothing here does I/O. These names are imported verbatim by Phases 3-11.
"""
from enum import StrEnum

LOCAL_CS = "https://upstream-onehealth.example/CodeSystem"


class SourceType(StrEnum):
    CSO = "cso"
    STORM_OUTFALL = "storm_outfall"
    INDUSTRIAL = "industrial"
    MISCONNECTION = "misconnection"
    DIFFUSE_RUNOFF = "diffuse_runoff"
    UNKNOWN = "unknown"


class ExposurePathway(StrEnum):
    RECREATION = "recreation"
    ANIMAL_CONTACT = "animal_contact"
    FLOODWATER = "floodwater"
    IRRIGATION = "irrigation"


class ObservationMethod(StrEnum):
    CITIZEN_VISUAL_OLFACTORY = "citizen_visual_olfactory"
    CITIZEN_FREETEXT = "citizen_freetext"
    CITIZEN_PHOTO = "citizen_photo"
    TEST_STRIP = "test_strip"
    SENSOR_TURBIDITY = "sensor_turbidity"
    SENSOR_CONDUCTIVITY = "sensor_conductivity"
    SENSOR_NORMAL_WINDOW = "sensor_normal_window"
    FIELD_TEST = "field_test"
    LAB_ECOLI = "lab_ecoli"
    LAB_ENTEROCOCCI = "lab_enterococci"
    OVERFLOW_TELEMETRY = "overflow_telemetry"
    BIOASSESSMENT = "bioassessment"


class PathogenClass(StrEnum):
    NOROVIRUS = "norovirus"
    CAMPYLOBACTER = "campylobacter"
    STEC = "stec"
    CRYPTOSPORIDIUM = "cryptosporidium"
    GIARDIA = "giardia"
    LEPTOSPIRA = "leptospira"


# PRD 7.6 incubation table -> (mean_days, sd_days) for a gamma fit.
INCUBATION_DAYS: dict[PathogenClass, tuple[float, float]] = {
    PathogenClass.NOROVIRUS: (1.25, 0.5),
    PathogenClass.CAMPYLOBACTER: (3.0, 1.0),
    PathogenClass.STEC: (3.5, 1.5),
    PathogenClass.CRYPTOSPORIDIUM: (7.0, 2.0),
    PathogenClass.GIARDIA: (10.5, 3.0),
    PathogenClass.LEPTOSPIRA: (9.5, 4.0),
}

SEWAGE_PATHOGEN_MIX: dict[PathogenClass, float] = {
    PathogenClass.NOROVIRUS: 0.35,
    PathogenClass.CAMPYLOBACTER: 0.25,
    PathogenClass.STEC: 0.10,
    PathogenClass.CRYPTOSPORIDIUM: 0.15,
    PathogenClass.GIARDIA: 0.15,
}

FLOODWATER_PATHOGEN_MIX: dict[PathogenClass, float] = {
    PathogenClass.LEPTOSPIRA: 0.4,
    PathogenClass.NOROVIRUS: 0.3,
    PathogenClass.CAMPYLOBACTER: 0.3,
}

CLINICAL_RELEVANCE_DAYS = 16  # PRD 6.1 "until about 16 days after exposure"
SYNDROME_SET = ["acute_gastroenteritis", "fever_after_floodwater_contact"]

# EU Bathing Water Directive 2006/7/EC Annex I, inland waters, the "poor" boundary.
# A quantitative lab result over this counts as a positive result for FR-21 sign-off;
# nothing else in the system turns a number into a yes/no, and inventing a private
# threshold would hide a public-health decision inside the kernel.
LAB_POSITIVE_THRESHOLD_PER_100ML: dict[ObservationMethod, float] = {
    ObservationMethod.LAB_ECOLI: 900.0,
    ObservationMethod.LAB_ENTEROCOCCI: 330.0,
}

# UCUM spellings we can convert to counts per 100 mL. Anything else fails closed:
# an unconvertible unit must never be read as "over the limit" (GC-13).
CFU_PER_100ML_FACTOR: dict[str, float] = {
    "{CFU}/(100.mL)": 1.0,
    "{CFU}/mL": 100.0,
    "{CFU}/dL": 1.0,
    "{CFU}/L": 0.1,
}
