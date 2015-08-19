from barcode import *

import base64
import struct
import skip32
import code128
import os

"""
Generate barcode CSV file

Exports a list with 2 columns: badge number, barcode
This can be used to send to the badge printer so they can print the numbers on all the badges.

Arguments:
filename (optional): if given, write to this file. if omitted, write to stdout
"""
@entry_point
def generate_all_barcodes_csv():
    outfile = sys.stdout if not len(sys.argv) > 1 else open(sys.argv[1],'w')

    sort_by_badge_start_num = lambda badge_range: badge_range[1][0]
    for (badge_type, (range_start, range_end)) in sorted(c.BADGE_RANGES.items(), key=sort_by_badge_start_num):
        for line in generate_barcode_csv(range_start, range_end):
            outfile.write(line)


def generate_barcode_csv(range_start, range_end):
    generated_lines = []
    seen_barcodes = []
    for badge_num in range(range_start, range_end+1):
        barcode_num = generate_barcode_from_badge_num(badge_num=badge_num)

        line = "{badge_num},{barcode_num}{newline}".format(
            badge_num=badge_num,
            barcode_num=barcode_num,
            newline=os.linesep
        )
        generated_lines.append(line)

        # ensure that we haven't seen this value before
        # We don't expect this to ever happen, but, never hurts to be paranoid.
        if barcode_num in seen_barcodes:
            raise ValueError("COLLISION: generated a badge# that's already been seen. change barcode key, try again")

        seen_barcodes.append(barcode_num)

    return generated_lines


def generate_barcode_from_badge_num(badge_num, event_id=None, salt=None, key=None):
    event_id = config['secret']['barcode_event_id'] if not event_id else event_id
    salt = config['secret']['barcode_salt'] if not salt else salt
    key = bytes(config['secret']['barcode_key'],'ascii') if not key else key

    if len(key) != 10:
        raise ValueError("key length should be exactly 10 bytes")

    # 4 bytes of data are going to be packed into an ecnrypted barcode:
    # byte 1        1 byte event ID
    # byte 2,3,4    24bit badge number (max badge# = 16million, more than reasonable)

    salted_val = badge_num + (0 if not salt else salt)

    if salted_val > 0xFFFFFF:
        raise ValueError("either badge_number or salt is too large " + str(badge_num))

    data_to_encrypt = struct.pack('>BI', event_id, salted_val)

    # remove the highest byte in that integer (2nd byte)
    data_to_encrypt = bytearray([data_to_encrypt[0], data_to_encrypt[2], data_to_encrypt[3], data_to_encrypt[4]])

    if len(data_to_encrypt) != 4:
        raise ValueError("data to encrypt should be 4 bytes")

    encrypted_string = _barcode_raw_encrypt(data_to_encrypt, key=key)

    # check to make sure it worked.
    decrypted = get_badge_num_from_barcode(encrypted_string, salt, key)
    if decrypted['badge_num'] != badge_num or decrypted['event_id'] != event_id:
        raise ValueError("internal algorithm error: verification did not decrypt correctly")

    # check to make sure this barcode number is valid for Code 128 barcode
    verify_barcode_is_valid_code128(encrypted_string)

    return encrypted_string


def get_badge_num_from_barcode(barcode_num, salt=None, key=None, event_id=None, verify_event_id_matches=True):
    event_id = config['secret']['barcode_event_id'] if not event_id else event_id
    salt = config['secret']['barcode_salt'] if not salt else salt
    key = bytes(config['secret']['barcode_key'],'ascii') if not key else key

    decrypted = _barcode_raw_decrypt(barcode_num, key=key)

    result = dict()

    result['event_id'] = struct.unpack('>B', bytearray([decrypted[0]]))[0]

    badge_bytes = bytearray(bytes([0, decrypted[1], decrypted[2], decrypted[3]]))
    result['badge_num'] = struct.unpack('>I', badge_bytes)[0] - salt

    if verify_event_id_matches and result['event_id'] != event_id:
        raise ValueError("error: event_id of decrypted barcode doesn't match our event ID."
                         "expected: " + str(event_id) + " got: " + str(result['event_id']))

    return result


def verify_barcode_is_valid_code128(encrypted_string):
    for c in encrypted_string:
        if c not in code128._charset_b:
            raise ValueError("contains a char not valid in a code128 barcode")


def _barcode_raw_encrypt(value, key):
    if len(value) != 4:
        raise ValueError("invalid barcode input: needs to be exactly 4 bytes")

    # skip32 generates 4 bytes output from 4 bytes input
    _encrypt = True
    skip32.skip32(key, value, _encrypt)

    # raw bytes aren't suitable for a Code 128 barcode though,
    # so convert it to base58 encoding
    # which is just some alphanumeric and numeric chars and is
    # designed to be vaguely human.  this takes our 4 bytes and turns it into 6 chars
    encrypted_value = base64.encodebytes(value).decode('ascii')

    # important note: because we are not an even multiple of 3 bytes, base64 needs to pad
    # the resulting string with equals signs.  we can strip them out knowing that our length is 4 bytes
    # IF YOU CHANGE THE LENGTH OF THE ENCRYPTED DATA FROM 4 BYTES, THIS WILL NO LONGER WORK.
    encrypted_value = encrypted_value.replace('==\n', '')

    if len(encrypted_value) != 6:
        raise ValueError("Barcode encryption failure: result should be 6 characters")

    return encrypted_value


def _barcode_raw_decrypt(value, key):
    # raw bytes aren't suitable for a Code 128 barcode though,
    # so convert it to base64 encoding
    # which is just some alphanumeric and numeric chars and is
    # designed to be vaguely human.  this takes our 4 bytes and turns it into 6ish bytes

    # important note: because we are not an even multiple of 3 bytes, base64 needs to pad
    # the resulting string with equals signs.  we can strip them out knowing that our length is 4 bytes
    # IF YOU CHANGE THE LENGTH OF THE ENCRYPTED DATA FROM 4 BYTES, THIS WILL NO LONGER WORK.

    if len(value) != 6:
        raise ValueError("Barcode decryption failure: result should be 6 characters")

    value += '==\n'

    decoded = base64.decodebytes(value.encode('ascii'))

    # skip32 generates 4 bytes output from 4 bytes input
    _encrypt = False
    decrytped = bytearray(decoded)
    skip32.skip32(key, decrytped, _encrypt)

    if len(decrytped) != 4:
        raise ValueError("invalid barcode input: needs to be exactly 4 bytes")

    return decrytped
