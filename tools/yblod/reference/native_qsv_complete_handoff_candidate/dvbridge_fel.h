/* SPDX-License-Identifier: GPL-3.0-or-later */
#ifndef DVBRIDGE_FEL_H
#define DVBRIDGE_FEL_H
#include <libavcodec/avcodec.h>
#include <stdbool.h>

struct dvbridge_fel;
/* Single decoder-thread owner. Returned frames retain their hardware surface. */
struct dvbridge_fel *dvbridge_fel_create(const AVCodecParameters *parameters, AVRational time_base);
void dvbridge_fel_destroy(struct dvbridge_fel *fel);
void dvbridge_fel_reset(struct dvbridge_fel *fel);
bool dvbridge_fel_device(struct dvbridge_fel *fel, AVBufferRef *device);
bool dvbridge_fel_submit(struct dvbridge_fel *fel, const AVPacket *packet);
bool dvbridge_fel_drain(struct dvbridge_fel *fel);
/* 1: exact pair, 0: need input, 2: discard preroll, -1: missing pair / failure. */
int dvbridge_fel_take(struct dvbridge_fel *fel, int64_t pts, AVFrame **frame);
bool dvbridge_fel_failed(const struct dvbridge_fel *fel);
/* Decoder reached EOF and no enhancement surface remains to pair. */
bool dvbridge_fel_exhausted(const struct dvbridge_fel *fel);
/* EL decoder choice, distinct from the renderer's QuickSync VPP setting.
 * Mapping count increments only after a successful direct QSV->VAAPI map. */
bool dvbridge_fel_qsv_selected(const struct dvbridge_fel *fel);
uint64_t dvbridge_fel_qsv_mapped_frames(const struct dvbridge_fel *fel);
/* Decoder-instance operation counters remain monotonic across seek/reset.
 * Paired counts exact returned EL frames, not native use or HDMI presentation. */
uint64_t dvbridge_fel_paired_frames(const struct dvbridge_fel *fel);
/* 1: genuinely mapped QSV frame, 0: unmarked VAAPI path, -1: malformed marker.
 * Marker is cleared on decoder output and set only after direct-map success. */
int dvbridge_fel_qsv_frame_route(const AVFrame *frame, uint64_t *map_sequence);
#endif
