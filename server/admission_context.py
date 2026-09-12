"""Compare validated physical admission metadata across transport sessions.

Only session id, admission epoch and binding digest are transport fields.
Everything else, including unknown future fields, remains part of the context.
This predicate grants no authority and does not replace session-owner checks.
"""
import re

TRANSPORT_FIELDS = frozenset({'session_id', 'admission_epoch', 'binding_digest'})


def same_admitted_context(before, after):
    def stable(metadata):
        if not isinstance(metadata, dict):
            return None
        binding = metadata.get('control_binding')
        if (not isinstance(binding, dict) or not isinstance(binding.get('context_generation'), str)
                or re.fullmatch('[0-9a-f]{32}', binding['context_generation']) is None):
            return None
        return {**metadata, 'control_binding': {key: value for key, value in binding.items() if key not in TRANSPORT_FIELDS}}
    left, right = stable(before), stable(after)
    return left is not None and right is not None and left == right
