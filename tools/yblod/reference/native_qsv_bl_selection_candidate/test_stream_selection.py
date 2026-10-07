"""Compile the candidate's actual selection block against a small route fixture."""
import json,subprocess,tempfile
from pathlib import Path
source=Path(__file__).with_name('DVDVideoCodecFFmpeg.cpp').read_text()
start=source.index('  const char* baseQsv = std::getenv("DVBRIDGE_BASE_QSV");')
end=source.index('\n#endif',start)
block=source[start:end]
assert block.count('return false;')==1 # Only a missing eligible QSV decoder is fatal.
fixture=r'''
#include <string>
#include <cstdlib>
#include <cstdio>
#include <cassert>
constexpr int AV_CODEC_ID_HEVC=173, CODEC_FORCE_SOFTWARE=1;
struct AVCodec{};
struct Hints { int codec=173,orientation=0,codecOptions=0;
    struct {int dv_profile=7,el_present_flag=1;} dovi; };
bool available=true;
const AVCodec* avcodec_find_decoder_by_name(const char* name) {
    static AVCodec decoder;
    assert(std::string(name)=="hevc_qsv");
    return available?&decoder:nullptr;
}
int select(Hints hints,bool m_dvNativeOutput) {
    bool m_dvBaseQsv=false;
    const AVCodec* pCodec=nullptr;
BLOCK
    return m_dvBaseQsv?1:0;
}
int main() {
    unsigned checks=0;
    for(int enabled: {0,1})for(int reconstruction: {0,1})for(int native: {0,1})
    for(int profile: {0,5,7,8})for(int hevc: {0,1})for(int el: {0,1})
    for(int rotated: {0,1})for(int software: {0,1})for(int decoder: {0,1}) {
        setenv("DVBRIDGE_BASE_QSV",enabled?"1":"0",1);
        setenv("DVBRIDGE_NATIVE_RECONSTRUCTION",reconstruction?"1":"0",1);
        Hints hints;hints.codec=hevc?173:27;hints.dovi={profile,el};
        hints.orientation=rotated?90:0;hints.codecOptions=software?1:0;
        available=decoder;
        const bool eligible=enabled && reconstruction && native && profile==7 && hevc && el && !rotated && !software;
        const int expected=eligible?(decoder?1:-1):0;
        assert(select(hints,native)==expected);checks++;
    }
    unsetenv("DVBRIDGE_BASE_QSV");unsetenv("DVBRIDGE_NATIVE_RECONSTRUCTION");
    assert(select(Hints{},true)==0);checks++;
    std::printf("{\"pass\":true,\"selection_cases\":%u,\"scope\":\"Actual selection block, not playback\"}\n",checks);
}
'''.replace('BLOCK',block.replace('return false;','return -1;'))
with tempfile.TemporaryDirectory(prefix='qsv-selection-') as root:
    src=Path(root)/'selection.cpp';binary=Path(root)/'selection'
    src.write_text(fixture)
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],check=True,timeout=30)
    result=subprocess.check_output([str(binary)],text=True,timeout=10)
    assert json.loads(result)['pass'] is True
    print(result,end='')
