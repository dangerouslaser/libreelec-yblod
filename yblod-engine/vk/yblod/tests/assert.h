/* YBLOD's assert for the C tests run by `cargo test` (yblod/tests): first on
 * the include path, so the ported CB1 tests' <assert.h> is this one. A
 * failed check is printed and counted (dvvk_test_failures), not an abort, so
 * the Rust test reports every failure. Not NDEBUG-dependent.
 * SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef YB_TEST_ASSERT_H
#define YB_TEST_ASSERT_H
void yb_test_check(int ok, const char *what, const char *file, int line);
#endif
#undef assert
#define assert(c) yb_test_check((c) != 0, #c, __FILE__, __LINE__)
