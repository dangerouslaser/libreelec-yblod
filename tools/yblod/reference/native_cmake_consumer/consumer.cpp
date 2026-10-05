#include <native_composer.h>
#include <native_colour.h>
#include <native_y416.h>

// Verify installed headers, exported target and C linkage from a C++ consumer.
int main()
{
    return yb_abi_version() == 1 && yb_colour_abi_version() == 1 &&
           yb_y416_sizeof_surface() == sizeof(yb_y416_surface) ? 0 : 1;
}
