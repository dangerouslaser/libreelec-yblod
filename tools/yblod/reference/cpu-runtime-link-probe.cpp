extern "C" int qsv_cpu_feature_probe() {
  return __builtin_cpu_supports("sse4.1");
}
