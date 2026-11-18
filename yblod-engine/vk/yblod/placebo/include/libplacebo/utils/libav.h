/*
 * This file is part of libplacebo.
 *
 * libplacebo is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * libplacebo is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with libplacebo. If not, see <http://www.gnu.org/licenses/>.
 */

/* YBLOD: the subset of libplacebo's <libplacebo/utils/libav.h> (e2972fdd,
 * CroqueMr's CB1 patches) that yblod/placebo/libav_dovi.c implements: the
 * Dolby Vision metadata mapping. */
#ifndef LIBPLACEBO_LIBAV_H_
#define LIBPLACEBO_LIBAV_H_

#include <libplacebo/colorspace.h>
#include <libavutil/dovi_meta.h>

PL_API_BEGIN

// Map Dolby Vision metadata into `struct pl_dovi_metadata`.
void pl_map_dovi_metadata(struct pl_dovi_metadata *out, const AVDOVIMetadata *data);

// Helper function for the common task of mapping Dolby Vision metadata to
// libplacebo's colour space and representation.
void pl_map_avdovi_metadata(struct pl_color_space *color, struct pl_color_repr *repr,
                            struct pl_dovi_metadata *dovi, const AVDOVIMetadata *metadata);

PL_API_END

#endif // LIBPLACEBO_LIBAV_H_
