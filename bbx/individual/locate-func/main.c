/*
 * Locate Function Definition
 *
 * Copyright (c) 2023 Kodanevhy Zhou
 *
 * To locate a function definition in C project. Inner filter is always fixed
 * in the code, outer filter comes from user.
 *
 * Usage:
 * locate-func-arm64 Func_Name grep filter1 grep filter2 ...
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

char *GREP = "grep";
char *connector = " | grep ";
char *sedConnector = " | sed ";

char cmd[100] = "grep -rn ";
char target[5] = " *.c\0";   // Only locate from C file.
char innerFilter[100];
char outerFilter[200];


int constructInnerFilter() {
    strcat(innerFilter, connector);
    strcat(innerFilter, "-v \";\"");
    strcat(innerFilter, sedConnector);
    // Remove result when matching 2 pairs of parentheses.
    strcat(innerFilter, "'/([(*(*))]/d'");
    return 0;
}


int main(int argc, char **argv, char **envp) {
    if (argc < 2) {
        printf("err: must accept a func.\n");
        goto exit;
    }

    char funcName[100];

    strcat(funcName, "\"");
    strcat(funcName, argv[1]);
    // Connect a "(" to funcName to ensure it's exactly a funcName.
    strcat(funcName, "(\"");
    strcat(cmd, funcName);
    if (argc == 2) {
        strcat(cmd, target);
    // >= 3
    } else {
        strcat(cmd, target);

        for (int i = 2; i <= argc - 1; i++) {
            if (strcmp(argv[i], GREP) == 0) {
                continue;
            }
            strcat(outerFilter, connector);
            strcat(outerFilter, argv[i]);
        }
    }

    constructInnerFilter();
    strcat(cmd, innerFilter);
    strcat(cmd, outerFilter);

    printf("%s: \"%s\"\n\n", "Going to execute", cmd);
    system(cmd);

    return 0;

    exit:
    return 1;
}
