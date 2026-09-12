"""Bounded cartridge bag decoding; duplicate item stacks are legal in Gen1."""
from server.gen1_native_trade_receipts import _bytes
from server.protocol_journal import JournalError

BALLS=frozenset((1,2,3,4))


def decode_bag(encoded):
    raw=_bytes(encoded,42);count=raw[0]
    if count>20 or raw[1+count*2]!=255:raise JournalError('invalid RBY bag count/terminator')
    rows=[]
    for slot in range(count):
        item,quantity=raw[1+slot*2:3+slot*2]
        if not 1<=item<=254 or not 1<=quantity<=99:raise JournalError('invalid RBY bag item/quantity')
        rows.append({'item':item,'quantity':quantity})
    return rows
