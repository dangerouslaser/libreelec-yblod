"""Declared raw-word->integer EL boundary alternatives, not a chosen policy.

Transport quantization, inverseEL accumulator floor and final12-bit rounding
are distinct operations. Unchanged integer reference arithmetic follows only
after declared quantization. Fractional formula extension remains hypothetical,
not a finite-float shader or licensed-player reconstruction model.
"""
import argparse
from collections import Counter
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path
import struct

import reference
import nlq_scaling_sensitivity as sensitivity

POLICIES=("floor","nearest-half-up","nearest-ties-even")
MAX_RAW=1023*64
NEUTRAL_RAW=512*64
MAPPED=32768


def candidate(raw,policy):
    """Stored16-bit word candidate; invalid native1024 is reported, not clipped."""
    reference.integer(raw,"storedrawword",0,65535)
    if policy not in POLICIES:raise ValueError("declare floor/nearest-half-up/nearest-ties-even")
    q,r=divmod(raw,64)
    if policy=="nearest-half-up":q=(raw+32)//64
    elif policy=="nearest-ties-even":q+=int(r>32 or r==32 and q%2==1)
    return {"native_code":q,"in_domain":0<=q<=1023}


def quantize(raw,policy):
    """Strict experiment API excludes raw/64 above native1023 for ALL policies.

    This is not the Y416 storage limit or a licensed limiting rule. In
    particular larger words may floor to1023 but remain outside this API.
    """
    reference.integer(raw,"nonovershootrawword",0,MAX_RAW)
    result=candidate(raw,policy)
    if not result["in_domain"]:raise ValueError("quantizednativecodeoutofdomain; noclamp")
    return result["native_code"]


def neutral_words():return list(range(NEUTRAL_RAW-128,NEUTRAL_RAW+129))


def whole_words():
    return [n*64+fraction for n in range(1024) for fraction in (0,16,32,48) if n*64+fraction<=MAX_RAW]


def _r(value):
    value=F(value);return [value.numerator,value.denominator]


def evaluate(raw,policy):
    native=quantize(raw,policy);sample=F(raw,64)
    residual=reference.inverse_el(native,sensitivity.PARAMETERS,10,23)
    hypothetical=sensitivity.formula_extension(sample)
    hypothetical_floor=hypothetical.numerator//hypothetical.denominator
    final=reference.reconstruct(MAPPED,residual,12)
    return {"raw_word":raw,"exact_native_sample":_r(sample),"quantized_native_code":native,
            "native_quantization_bias":_r(native-sample),"integer_reference_residual":residual,
            "synthetic_reconstructed_12bit":final,
            "hypothetical_unquantized_formula_residual":_r(hypothetical),
            "hypothetical_final_floor_residual":hypothetical_floor,
            "hypothetical_reconstructed_12bit":sensitivity.reconstruct_extension(MAPPED,hypothetical),
            "hypothetical_final_floor_reconstructed_12bit":reference.reconstruct(MAPPED,hypothetical_floor,12),
            "residual_error_vs_hypothetical_formula":_r(residual-hypothetical),
            "residual_error_vs_hypothetical_final_floor":residual-hypothetical_floor,
            "reconstructed_error_vs_hypothetical_formula":final-sensitivity.reconstruct_extension(MAPPED,hypothetical),
            "reconstructed_error_vs_hypothetical_final_floor":final-reference.reconstruct(MAPPED,hypothetical_floor,12)}


def _hist(values):
    counts=Counter(F(v) for v in values)
    return [{"value":_r(v),"count":counts[v]} for v in sorted(counts)]


def _sign(value):return (value>0)-(value<0)


def _scope(words,policy,keep_rows=False):
    rows=[evaluate(raw,policy) for raw in words]
    zeros=[r["raw_word"] for r in rows if r["integer_reference_residual"]==0]
    biases=[F(*r["native_quantization_bias"]) for r in rows]
    transitions=[]
    for before,after in zip(rows,rows[1:]):
        if before["quantized_native_code"]!=after["quantized_native_code"]:
            transitions.append({"previous_raw_word":before["raw_word"],"raw_word":after["raw_word"],
                                "native_from":before["quantized_native_code"],"native_to":after["quantized_native_code"],
                                "residual_from":before["integer_reference_residual"],"residual_to":after["integer_reference_residual"],
                                "reconstructed12_from":before["synthetic_reconstructed_12bit"],"reconstructed12_to":after["synthetic_reconstructed_12bit"]})
    def decreases(key):
        values=[F(*r[key]) if isinstance(r[key],list) else r[key] for r in rows]
        return sum(b<a for a,b in zip(values,values[1:]))
    result={"samples":len(rows),"input_raw_words_sha256":hashlib.sha256(struct.pack("<"+"H"*len(words),*words)).hexdigest(),
            "evaluated_rows_sha256":hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(",",":")).encode()).hexdigest(),
            "native_quantization_bias_histogram":_hist(biases),"mean_native_quantization_bias":_r(sum(biases,F(0))/len(biases)),
            "residual_error_histogram_vs_hypothetical_formula":_hist(F(*r["residual_error_vs_hypothetical_formula"]) for r in rows),
            "residual_error_histogram_vs_hypothetical_final_floor":_hist(r["residual_error_vs_hypothetical_final_floor"] for r in rows),
            "reconstruction12_error_histogram_vs_hypothetical_formula":_hist(r["reconstructed_error_vs_hypothetical_formula"] for r in rows),
            "reconstruction12_error_histogram_vs_hypothetical_final_floor":_hist(r["reconstructed_error_vs_hypothetical_final_floor"] for r in rows),
            "policy_transitions":transitions,
            "zero_residual_span":{"first_raw_word":min(zeros),"last_raw_word":max(zeros),"sampled_zero_count":len(zeros),
                                  "every_raw_word_in_span_sampled_zero":zeros==list(range(min(zeros),max(zeros)+1)),
                                  "native_sample_endpoints":[_r(F(min(zeros),64)),_r(F(max(zeros),64))]},
            "nonneutral_suppressed_count":sum(r["raw_word"]!=NEUTRAL_RAW and r["integer_reference_residual"]==0 for r in rows),
            "monotonicity_decreases":{"quantized_native":decreases("quantized_native_code"),"integer_residual":decreases("integer_reference_residual"),
                                      "reconstructed12":decreases("synthetic_reconstructed_12bit"),
                                      "hypothetical_unquantized_formula":decreases("hypothetical_unquantized_formula_residual"),
                                      "hypothetical_final_floor":decreases("hypothetical_final_floor_residual")},
            "sign_checks":{"integer_residual_wrong_sign_vs_quantized_native":sum(_sign(r["integer_reference_residual"])*_sign(r["quantized_native_code"]-512)<0 for r in rows),
                           "integer_residual_wrong_sign_vs_raw_sample":sum(_sign(r["integer_reference_residual"])*_sign(r["raw_word"]-NEUTRAL_RAW)<0 for r in rows),
                           "hypothetical_formula_wrong_sign_vs_raw_sample":sum(_sign(F(*r["hypothetical_unquantized_formula_residual"]))*_sign(r["raw_word"]-NEUTRAL_RAW)<0 for r in rows)}}
    if keep_rows:result["rows"]=rows
    return result


def report():
    anchors=[]
    for n in range(1024):
        residual=reference.inverse_el(n,sensitivity.PARAMETERS,10,23)
        policies={p:quantize(n*64,p) for p in POLICIES}
        extension=sensitivity.formula_extension(F(n))
        if any(q!=n for q in policies.values()) or extension!=residual:raise AssertionError("integeranchormismatch")
        anchors.append([n,residual,reference.reconstruct(MAPPED,residual,12)])
    guards=[]
    for raw in (-1,0,1,MAX_RAW,MAX_RAW+1,65503,65504,65535,65536):
        row={"raw_word":raw,"policies":{}}
        for policy in POLICIES:
            outcome={}
            try:outcome["stored_word_candidate"]=candidate(raw,policy)
            except ValueError:outcome["stored_word_candidate"]={"accepted":False}
            try:outcome["strict_experiment_api"]={"accepted":True,"native_code":quantize(raw,policy)}
            except ValueError:outcome["strict_experiment_api"]={"accepted":False}
            row["policies"][policy]=outcome
        guards.append(row)
    return {"schema":"yblod.nlq-integer-boundary.v1","status":"complete",
            "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "helper_sha256":{Path(m.__file__).name:hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest() for m in (reference,sensitivity,sensitivity.geometry)},
            "parameters":dict(sensitivity.PARAMETERS),"el_bit_depth":10,"coefficient_log2_denom":23,"synthetic_mapped_bl_code":MAPPED,"output_bit_depth":12,
            "strict_experiment_raw_domain":[0,MAX_RAW],"stored_word_candidate_domain":[0,65535],
            "domain_interpretation":"strictAPI restriction preserves hypotheticalextension native0..1023domain; NOTY416storage or licensedlimiting behavior; validfloor1023 beyond65472 stillrejectedbystrictAPI",
            "operation_order":["declaredtransportquantization","unchangedintegerreference.inverse_el including accumulatorfloor","unchangedreference.reconstruct final12bitround+bound"],
            "policy_definitions":{"floor":"floor(raw/64)","nearest-half-up":"floor(raw/64+1/2)","nearest-ties-even":"nearest integer; exacthalf chooses even"},
            "integer_anchor_checks":{"samples":1024,"all_policies_equal_native_anchors":True,"formula_extension_equals_integer_reference":True,
                                     "anchor_rows_sha256":hashlib.sha256(json.dumps(anchors,separators=(",",":")).encode()).hexdigest()},
            "endpoint_guards":guards,
            "policies":{p:{"neutral_step1_sweep":_scope(neutral_words(),p,True),"whole_range_anchors_and_quarters":_scope(whole_words(),p)} for p in POLICIES},
            "limitations":["no policy selected, no production changes or output matching","fractional formula extension is hypothetical, not normative or a finitefloat shader emulator",
                           "synthetic mappedBL and one declared metadata fixture, not a real-frame or SK4 prediction","raw1024 candidates never enter inverseEL and are never clamped"]}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("output",type=Path);args=parser.parse_args()
    value=report()
    with args.output.open("x") as handle:json.dump(value,handle,indent=2,sort_keys=True);handle.write("\n")
