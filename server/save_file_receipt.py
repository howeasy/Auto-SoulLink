"""Generation-neutral remote SaveRAM image/receipt checks; never opens a path."""
import copy
import hashlib

from server.protocol_journal import JournalError


def verify_file_image(proof, image, *, host_profile, frame_from, frame_to):
    fields={"schema","path","sha256","byte_length","host_profile","frame","flushed","readback"}
    if (type(image) is not bytes or not 0<len(image)<=1024*1024
            or not isinstance(proof,dict) or set(proof)!=fields or proof["schema"]!="slink-saveram-file-v1"
            or proof["flushed"] is not True or proof["readback"] is not True
            or type(proof["byte_length"]) is not int or proof["byte_length"]!=len(image)
            or proof["sha256"]!=hashlib.sha256(image).hexdigest() or proof["host_profile"]!=host_profile
            or not isinstance(proof["path"],str) or not 1<=len(proof["path"])<=4096
            or any(ord(c)<32 for c in proof["path"]) or type(proof["frame"]) is not int):
        raise JournalError("owned complete SaveRAM file proof differs")
    if (type(frame_from) is not int or type(frame_to) is not int
            or not 0<=frame_from<=proof["frame"]<=frame_to<=2**53-1):
        raise JournalError("file flush is outside the owned native frame window")
    return copy.deepcopy(proof)
