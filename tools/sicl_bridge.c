/*
 * Minimal SICL bridge for Keysight GPIB adapters.
 *
 * Usage:
 *   sicl_bridge.exe <sicl-address> [timeout-ms]
 *   example: sicl_bridge.exe gpib0,1 10000
 *
 * Protocol on stdin/stdout, one record per line:
 *   Q:[timeout:]scpi  write command, read response -> O:<response>
 *   R:<timeout>       read response only           -> O:<response>
 *   W:<scpi>          write command without reading -> O:
 *   X                 close and exit
 *
 * Errors are reported as E:<sicl-status>.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "sicl.h"

#define MAX_LINE 8192
#define MAX_REPLY 65536

static void strip_eol(char *text, size_t length)
{
    while (length > 0) {
        char ch = text[length - 1];
        if (ch != '\r' && ch != '\n') {
            break;
        }
        text[--length] = '\0';
    }
}

int main(int argc, char **argv)
{
    INST id;
    char line[MAX_LINE];
    char reply[MAX_REPLY + 1];
    unsigned long written = 0;
    int status;

    if (argc < 2 || argc > 3) {
        fprintf(stderr, "usage: %s <sicl-address> [timeout-ms]\n", argv[0]);
        return 2;
    }

    id = iopen(argv[1]);
    if (id < 0) {
        printf("E:%d\n", id);
        fflush(stdout);
        return 1;
    }
    itimeout(id, argc == 3 ? atoi(argv[2]) : 10000);
    setvbuf(stdout, NULL, _IONBF, 0);

    while (fgets(line, sizeof(line), stdin) != NULL) {
        size_t length = strlen(line);
        char kind;
        char *command;

        strip_eol(line, length);
        length = strlen(line);
        kind = (char)toupper((unsigned char)line[0]);
        if (kind == 'X') {
            break;
        }
        if (length < 2) {
            continue;
        }
        if (line[1] != ':' || (kind != 'Q' && kind != 'W' && kind != 'R')) {
            printf("E:bad-command\n");
            continue;
        }

        command = line + 2;
        if (kind == 'Q' || kind == 'R') {
            char *end = NULL;
            long timeout = strtol(command, &end, 10);
            if (end != command && *end == ':') {
                itimeout(id, (int)timeout);
                command = end + 1;
            }
        }

        if (kind != 'R') {
            status = iwrite(id, command, (unsigned long)strlen(command),
                            1, &written);
            if (status < 0) {
                printf("E:%d\n", status);
                continue;
            }
            if (kind == 'W') {
                printf("O:\n");
                continue;
            }
        }

        {
            int reason = 0;
            unsigned long received = 0;
            status = iread(id, reply, MAX_REPLY, &reason, &received);
            if (status < 0) {
                printf("E:%d\n", status);
                continue;
            }
            if (received > MAX_REPLY) {
                received = MAX_REPLY;
            }
            reply[received] = '\0';
            strip_eol(reply, received);
            printf("O:%s\n", reply);
        }
    }

    iclose(id);
    return 0;
}
