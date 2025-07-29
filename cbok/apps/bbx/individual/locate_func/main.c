/*
 * Locate Function Definition
 *
 * Copyright (c) 2023 Kodanevhy Zhou
 *
 * To locate a function definition in C project. Inner filter is always fixed
 * in the code, outer filter comes from user.
 *
 * Usage:
 * locate-func-arm64 Func_Name --debug
 *
 * --debug: Open the debug mode.
 */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#define bool int

bool debug = 1;

char *connector = " | grep ";
char *sedConnector = " | sed ";

char cmd[500] = "grep -rn ";
char target[17] = " --include=\"*.c\"\0";   // Only locate from C file.
char innerFilter[100];
char outerFilter[200];


int constructInnerFilter() {
    strcat(innerFilter, connector);
    strcat(innerFilter, "-v \";\"");

    strcat(innerFilter, connector);
    strcat(innerFilter, "-v \"=\"");

    // Remove funcName in single line comment.
    strcat(innerFilter, connector);
    strcat(innerFilter, "-v \"//\"");

    // Remove result when matching 2 pairs of parentheses.
    strcat(innerFilter, sedConnector);
    strcat(innerFilter, "'/.*(.*(.*/d'");
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
            if (strcmp(argv[i], "--debug") == 0)
            {
                debug = 0;
                continue;
            }
        }
    }

    constructInnerFilter();
    strcat(cmd, innerFilter);
    strcat(cmd, outerFilter);

    if (debug == 0) {
        printf("%s: \"%s\"\n", "Going to execute", cmd);
    }
    system(cmd);

    return 0;

    exit:
    return 1;
}
