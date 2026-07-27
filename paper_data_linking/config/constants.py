# ./config/constants.py
from enum import Enum

class DataFields(Enum):
    BIBCODE = "bibcode"
    TEXT = "text"
    TOKEN_COUNT = "token_count"
    VALID = "valid"

NO_VSO_SOURCES_FLAG = "NO_VSO_SOURCES"