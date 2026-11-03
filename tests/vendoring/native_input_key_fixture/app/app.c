#include <stdio.h>

#include "h1.h"
#include "lib.h"

int b_value(void);

int main(void) {
    printf("h1=%d h2=%d h3=%d lib2=%d\n", H1_VALUE, b_value(), lib_h3(), lib_two());
    return 0;
}
