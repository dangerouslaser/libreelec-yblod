# Independent reusable base mapping

`base_mapping_stage.py` implements the integer polynomial and multi-channel
regression (MMR) base-layer mappings without calling or importing the existing
reference. `BaseMappingConfig` validates and copies the mapping into immutable
tuples; `map_sample` maps one explicit Y/Cb/Cr triplet, and `iter_mapped` handles
triplets lazily.

Each input is a whole native 8-bit or 10-bit code. The scalar module accepts
denominators 13 through 32; complete-frame validation additionally checks the
denominator against enhancement depth. Metadata bounds follow the existing
manifest envelope, not a full RPU or bitstream-conformance validator.

Internal pivot boundaries select the interval to their right, with the last
interval owning the upper endpoint. Every channel is separately bounded by its
own pivot endpoints before MMR. Polynomial accumulation and MMR's intermediate
fixed-point floors are preserved; final mapping is bounded to 0 through 65535.
No individual signed term is clipped before summation.

MMR is supported only for chroma mappings. The caller supplies the prepared
luma guide explicitly as the triplet's first value; the mapper neither chooses
a sampling position nor expands chroma. Guide preparation and enhancement
scaling remain outside this arithmetic stage.

Seven tests cover 92160 comparisons with the unchanged reference plus literal
polynomial, pivot and MMR answers. Near-full-scale cross-product tests also
compare independent exact-fraction term calculations, including intermediate
floors. Configuration mutation, invalid values and lazy consumption are tested.
These are arithmetic checks, not licensed-player matching or Dolby certification.

`STREAMING_COMPOSER.md` describes the prepared-frame runner assembling this
mapper with the correction and composition stages.
