/* Offline same-build instruction ABI to canonical composer wire metadata.
 * No GL objects are touched; synthetic texture names satisfy CPU plan guards. */
#include "native_dovi_adapter.h"
#include "native_gpu_composer_backend.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int dimension(const char *s,uint32_t limit,uint32_t *out)
{
 uint32_t value=0;if(!*s)return 0;
 for(;*s;s++){if(*s<'0'||*s>'9'||value>limit/10U)return 0;value=value*10U+(uint32_t)(*s-'0');if(value>limit)return 0;}
 if(!value||(value&1U))return 0;
 *out=value;return 1;
}
int main(int argc,char **argv)
{
 if(argc!=5){fprintf(stderr,"usage: exporter instructions.bin width height NEW_OUTPUT\n");return 2;}
 const uint16_t endian=1;if(*(const unsigned char *)&endian!=1)return 2;
 yb_gpu_backend_plan plan={0};
 if(!dimension(argv[2],3840,&plan.width)||!dimension(argv[3],2160,&plan.height))return 2;
 yb_dovi_integer_instructions instruction;
 if(sizeof(instruction)!=9216)return 1;
 FILE *input=fopen(argv[1],"rb");if(!input)return 1;
 int okay=fread(&instruction,1,sizeof(instruction),input)==sizeof(instruction);
 if(fgetc(input)!=EOF||ferror(input))okay=0;
 if(fclose(input))okay=0;
 if(!okay||instruction.version!=1||instruction.residual_enabled!=1)return 1;
 plan.version=1;plan.input_format=YB_GPU_INPUT_NORMALIZED_P010_WHOLE_GUIDE10;
 plan.enhancement_enabled=1;plan.output_depth=instruction.output_depth;
 plan.mapping=instruction.mapping;memcpy(plan.nlq,instruction.nlq,sizeof(plan.nlq));
 plan.frame_id[0]=1;plan.guide_frame_id[0]=1;plan.enhancement_frame_id[0]=1;
 plan.guide_contract_id[0]=2;plan.enhancement_scale_contract_id[0]=2;
 for(unsigned i=0;i<5;i++)plan.textures[i]=i+1U;
 int64_t words[3][419];
 for(uint32_t c=0;c<3;c++)if(yb_gpu_backend_pack_metadata(&plan,c,words[c])!=YB_GPU_BACKEND_OK)return 1;
 FILE *output=fopen(argv[4],"wbx");if(!output)return 1;
 okay=fwrite(words,1,sizeof(words),output)==sizeof(words);
 if(fclose(output))okay=0;
 if(!okay)return 1;
 printf("{\"components\":3,\"words_per_component\":419,\"word_format\":\"int64le\",\"bytes\":%zu}\n",sizeof(words));
 return 0;
}
