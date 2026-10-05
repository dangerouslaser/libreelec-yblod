"""Explicit exact-coordinate sampling diagnostics; no production filter policy."""
from dataclasses import dataclass
from fractions import Fraction


def integer(value,name,low,high):
    if type(value) is not int or not low<=value<=high:raise ValueError(f"{name}: strict integer {low}..{high} required")
    return value


def dyadic(value,name):
    if type(value) not in (int,Fraction):raise ValueError(f"{name}: exact integer/Fraction required")
    result=Fraction(value);den=result.denominator
    if den&(den-1) or den>65536 or abs(result)>8192:raise ValueError(f"{name}: bounded dyadic coordinate required")
    return result


@dataclass(frozen=True)
class SamplingContract:
    width:int
    height:int
    origin_x:Fraction
    origin_y:Fraction
    step_x:Fraction
    step_y:Fraction
    method:str
    word_normalization_divisor:int
    edge:str="replicate"
    native_depth:int=10
    fractional_bits:int=6

    def __post_init__(self):
        integer(self.width,"width",1,8192);integer(self.height,"height",1,8192)
        for name in ("origin_x","origin_y","step_x","step_y"):object.__setattr__(self,name,dyadic(getattr(self,name),name))
        if type(self.method) is not str or self.method not in ("integer-point","bilinear"):raise ValueError("explicit diagnostic method required")
        if self.edge!="replicate" or type(self.edge) is not str:raise ValueError("replicate boundary declaration required")
        if type(self.native_depth) is not int or self.native_depth!=10 or type(self.fractional_bits) is not int or self.fractional_bits!=6:
            raise ValueError("only explicitly declared native10-Q6 colour route supported")
        integer(self.word_normalization_divisor,"word_normalization_divisor",1,(1<<32)-1)

    @property
    def coordinate_fractional_bits(self):
        return max(getattr(self,n).denominator.bit_length()-1 for n in ("origin_x","origin_y","step_x","step_y"))

    def source_coordinate(self,x,y):
        integer(x,"output x",0,8191);integer(y,"output y",0,8191)
        return self.origin_x+self.step_x*x,self.origin_y+self.step_y*y

    def native_fields(self):
        bits=self.coordinate_fractional_bits;den=1<<bits
        return {"width":self.width,"height":self.height,"origin_x":int(self.origin_x*den),"origin_y":int(self.origin_y*den),
                "step_x":int(self.step_x*den),"step_y":int(self.step_y*den),"coordinate_fractional_bits":bits,
                "method":1 if self.method=="integer-point" else 2,"edge":1,"native_depth":10,"fractional_bits":6,
                "word_normalization_divisor":self.word_normalization_divisor}


def sample_exact(rows,x,y,contract):
    """Independent stdlib oracle. Rows are raw u16 colour words, not alpha.

    Full declared plane geometry is required. This oracle is not the native
    playback path; no output is rounded, clipped or passed to integer NLQ.
    """
    if type(contract) is not SamplingContract:raise ValueError("validated SamplingContract required")
    if len(rows)!=contract.height or any(len(row)!=contract.width for row in rows):raise ValueError("declared complete plane required")
    if any(type(v) is not int or not 0<=v<=65535 for row in rows for v in row):raise ValueError("raw unsigned16 plane required")
    sx,sy=contract.source_coordinate(x,y)
    def at(ix,iy):return rows[min(max(iy,0),contract.height-1)][min(max(ix,0),contract.width-1)]
    if contract.method=="integer-point":
        if sx.denominator!=1 or sy.denominator!=1:raise ValueError("integer-point rejects fractional coordinates")
        raw=Fraction(at(int(sx),int(sy)))
    else:
        ix=sx.numerator//sx.denominator;iy=sy.numerator//sy.denominator;tx=sx-ix;ty=sy-iy
        raw=(1-ty)*((1-tx)*at(ix,iy)+tx*at(ix+1,iy))+ty*((1-tx)*at(ix,iy+1)+tx*at(ix+1,iy+1))
    return {"source_coordinate":(sx,sy),"raw_word":raw,"native_equivalent":raw/64,
            "diagnostic_normalized":raw/contract.word_normalization_divisor}
