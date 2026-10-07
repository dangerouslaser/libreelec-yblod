from pathlib import Path
import subprocess
import tempfile

source = Path(__file__).with_name('DVBridgeGLES.cpp').read_text()
start = source.index('  if (elRoute < 0 ||')
end = source.index('  m_elDecoderQsv =', start)
guard = source[start:end].replace('return Failure("el-qsv-route-proof");', 'return false;')
fixture = '''#include <cstring>
bool accepted(bool enhancement, const char* qsvFlag, int elRoute) {
''' + guard + '''return true; }
int main() {
 const char* flags[] = {nullptr,"0","1","invalid"};
 for (bool el : {false,true}) for (const char* flag : flags)
 for (int route=-1;route<=1;route++) {
   bool expected = route >= 0 && (!flag || !std::strcmp(flag,"0") || !std::strcmp(flag,"1"))
     && !(el && flag && !std::strcmp(flag,"1") && route != 1);
   if (accepted(el,flag,route) != expected) return 1;
 }
 if (!accepted(false,"1",0) || accepted(true,"1",0) || !accepted(true,"1",1)) return 2;
}
'''
fixture = '#include <initializer_list>\n' + fixture
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path/'test.cpp').write_text(fixture)
    subprocess.run(['c++','-std=c++17',str(path/'test.cpp'),'-o',str(path/'test')],check=True)
    subprocess.run([str(path/'test')],check=True)
print('PASS: 24 renderer route combinations; P8 no-EL accepted; FEL proof retained')
