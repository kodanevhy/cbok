#include <stdio.h>
#include <string.h>
#include <stdlib.h>

char *GREP = "grep";
char *connector = " | grep ";


int main(int argc, char **argv, char **envp) {
    if (argc < 2) {
        printf("err: must accept a func.\n");
        goto exit;
    }

    char total_cmd[100] = "grep -rn ";
    char *target;
    char grep_str[100];

    strcat(total_cmd, argv[1]);
    if (argc == 2) {
        target = " .\0";
        strcat(total_cmd, target);
    // >= 3
    } else {
        target = " . | grep \0";
        strcat(total_cmd, target);

        for (int i = 2; i <= argc - 1; i++) {
            if (strcmp(argv[i], GREP) == 0) {
                continue;
            }
            strcat(grep_str, argv[i]);
            // The last space will be redundant to add to the command, so skip adding
            // the (argc - 1) space char.
            if (i != (argc - 1)) {
                strcat(grep_str, connector);
            }
        }
    }
    strcat(total_cmd, grep_str);

    printf("%s: \"%s\"\n", "Going to execute", total_cmd);
    system(total_cmd);

    return 0;

    exit:
    return 1;
}
