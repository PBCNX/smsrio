# Copyright (C) 2026 The SMSRio Open Driver Authors
# SPDX-License-Identifier: GPL-2.0-or-later
# smsrio-pbcnx

"""ISDB-T TMCC as the Siano's 653 statistics message reports it.

The demod has already parsed TMCC; these are the demod's own values, not a
register block we decode.  Layout from the kernel `struct sms_isdbt_stats_ex`
(drivers/media/common/siano/smscoreapi.h, GPL-2.0-or-later) and the
`sms_isdbt_layer_stats` blocks, validated against the live 479/485/497 records
(2026-11-20) and a reference set of broadcast records.  Unknown stays None, never 0.
"""

MODE_LABELS = {1: "2K", 2: "4K", 3: "8K"}
MODE_CANONICAL = {1: 0, 2: 1, 3: 2}
GUARD_LABELS = {1: "1/32", 2: "1/16", 3: "1/8", 4: "1/4"}
# The Siano's constellation enum: 0 QPSK, 1 16QAM, 2 64QAM (3 DQPSK).
CONSTELLATION_LABELS = {0: "QPSK", 1: "16QAM", 2: "64QAM", 3: "DQPSK"}
CODE_RATE_LABELS = {0: "1/2", 1: "2/3", 2: "3/4", 3: "5/6", 4: "7/8"}
# ti_ldepth_i is the depth, not an index: 2 = I2, 4 = I4.
INTERLEAVE_LABELS = {0: "I0", 1: "I1", 2: "I2", 4: "I4"}
INTERLEAVE_CANONICAL = {0: 0, 1: 1, 2: 2, 4: 3}

MODE = 12
MODEM_STATE = 13
GUARD = 14
SYSTEM = 15
PARTIAL = 16
LAYERS = 17
SEGMENTS = 18
TUNE_BW = 19
LAYER_BASE = 20
LAYER_STRIDE = 12
EWS = 59  # ews_alert_active

# sms_isdbt_layer_stats fields, in words from the layer base.
CODE_RATE = 0
CONSTELLATION = 1
BER = 2
TI_LDEPTH_I = 9
NUMBER_OF_SEGMENTS = 10
TMCC_ERRORS = 11
UNUSED = 255


def parse(words):
    """Return the Tmcc record from the u32 words of a 654 body, or None if short."""
    if len(words) < 20:
        return None
    record = {
        "source": "demod 653 statistics",
        "mode": words[MODE],
        "mode_label": MODE_LABELS.get(words[MODE]),
        "mode_canonical": MODE_CANONICAL.get(words[MODE]),
        "guard": words[GUARD],
        "guard_label": GUARD_LABELS.get(words[GUARD]),
        "partial": bool(words[PARTIAL]),
        "num_layers": words[LAYERS],
        "segment_number": words[SEGMENTS],
        "tune_bw": words[TUNE_BW],
        "system_type": words[SYSTEM],
        "modem_state": words[MODEM_STATE],
        "layers": [],
        "raw": list(words[12:]),
    }
    for index in range(3):
        base = LAYER_BASE + index * LAYER_STRIDE
        if base + LAYER_STRIDE > len(words):
            break
        code_rate = words[base + CODE_RATE]
        constellation = words[base + CONSTELLATION]
        interleave = words[base + TI_LDEPTH_I]
        segments = words[base + NUMBER_OF_SEGMENTS]
        present = (code_rate != UNUSED and segments > 0
                   and index < record["num_layers"])
        record["layers"].append({
            "index": index,
            "code_rate": code_rate,
            "code_rate_label": CODE_RATE_LABELS.get(code_rate),
            "constellation": constellation,
            "constellation_label": CONSTELLATION_LABELS.get(constellation),
            "ber": words[base + BER],
            "interleaving": interleave,
            "interleaving_label": INTERLEAVE_LABELS.get(interleave),
            "interleaving_canonical": INTERLEAVE_CANONICAL.get(interleave),
            "segments": segments,
            "tmcc_errors": words[base + TMCC_ERRORS],
            "present": present,
        })
    # The family validity gate (IT9175's zero trap): an undecoded block reads as zeros, which
    # decodes into a plausible 2K/1/32 picture with no layers. A reading is a channel only when
    # the mode and guard are known and 1..13 segments are claimed by present layers.
    segments = sum(layer["segments"] for layer in record["layers"] if layer["present"])
    record["valid"] = (record["mode_label"] is not None
                       and record["guard_label"] is not None
                       and 1 <= segments <= 13)
    record["ews"] = bool(words[EWS]) if record["valid"] and len(words) > EWS else None
    return record


def format_line(khz, record):
    """One line for the CLI: label and index together, never a bare number."""
    if not record:
        return "%d kHz tmcc n/a" % khz
    if not record.get("valid", True):
        return ("%d kHz tmcc not decoded yet (no layer segments - the demod has not decoded "
                "TMCC on this channel)" % khz)
    parts = ["%d kHz tmcc" % khz]
    if record["mode_label"]:
        parts.append("mode %s (%d)" % (record["mode_label"], record["mode"]))
    if record["guard_label"]:
        parts.append("guard %s (%d)" % (record["guard_label"], record["guard"]))
    parts.append("partial %d" % int(record["partial"]))
    parts.append("layers %d" % record["num_layers"])
    if record["ews"] is not None:
        parts.append("ews %d" % int(record["ews"]))
    for layer in record["layers"]:
        if not layer["present"]:
            continue
        parts.append("L%d:%s %dseg code %s (%d) %s" % (
            layer["index"],
            layer["constellation_label"] or "?",
            layer["segments"],
            layer["code_rate_label"] or "?",
            layer["code_rate"],
            layer["interleaving_label"] or "?"))
    return " ".join(parts)

