"""Schema identifiers and compatibility sets (V2.2 10.4 / 16.3 / 27.1)."""

MESSAGE_SCHEMA_ID = 'boom_birds.message.v2.0'
ACTION_SCHEMA_ID = 'boom_birds.action.v2.0'
ACTION_FRAME = 'COMPOSITE_BODY_HEADING_FLU_WORLD_UP'
ACTION_UNITS = 'm/s,rad/s'

SUPPORTED_MESSAGE_SCHEMAS = frozenset({MESSAGE_SCHEMA_ID})
SUPPORTED_ACTION_SCHEMAS = frozenset({ACTION_SCHEMA_ID})
