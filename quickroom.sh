#!/usr/bin/env bash
# ==============================================================================
# U of T QuickRoom Finder - Daemon & CLI Manager
# Runs server.py in an isolated, permanent tmux session on an obscure port.
# ==============================================================================

set -o pipefail

# Configuration
PORT="${PORT:-29842}"
SESSION_NAME="uoft-quickroom"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/server.py"
LOG_FILE="$SCRIPT_DIR/server.log"
PYTHON_BIN="$(which python3 2>/dev/null || echo "python3")"

# Remote host identification
HOSTNAME_VAL="$(hostname -f 2>/dev/null || hostname 2>/dev/null || echo "localhost")"
IP_VAL="$(hostname -I 2>/dev/null | awk '{print $1}')"

# ANSI color codes
BOLD='\033[1m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

is_tmux_running() {
    tmux has-session -t "$SESSION_NAME" 2>/dev/null
}

is_port_listening() {
    ss -tuln 2>/dev/null | grep -q ":${PORT}\b"
}

get_status_line() {
    if is_tmux_running; then
        if is_port_listening; then
            echo -e "${GREEN}${BOLD}RUNNING${NC} (tmux session '${SESSION_NAME}' active, port ${CYAN}${PORT}${NC} listening)"
        else
            echo -e "${YELLOW}${BOLD}STARTING / IDLE${NC} (tmux session active, waiting on port ${PORT})"
        fi
    else
        if is_port_listening; then
            echo -e "${YELLOW}${BOLD}PORT IN USE${NC} (port ${PORT} bound, but outside '${SESSION_NAME}')"
        else
            echo -e "${RED}${BOLD}STOPPED${NC}"
        fi
    fi
}

start_server() {
    echo -e "\n${BOLD}=== 1. Starting QuickRoom Server ===${NC}"
    if is_tmux_running; then
        echo -e "${YELLOW}Server is already running in tmux session '${SESSION_NAME}'.${NC}"
        print_urls
        return 0
    fi

    if is_port_listening; then
        echo -e "${RED}Warning: Port ${PORT} is already in use by another process.${NC}"
        echo -e "Attempting to release port ${PORT}..."
        fuser -k -n tcp "$PORT" 2>/dev/null
        sleep 1
    fi

    # Ensure log file exists
    touch "$LOG_FILE"

    echo -e "Launching tmux session '${CYAN}${SESSION_NAME}${NC}'..."
    # The while loop ensures that if the Python server ever exits unexpectedly,
    # the tmux session stays up and automatically restarts the server.
    tmux new-session -d -s "$SESSION_NAME" "cd \"$SCRIPT_DIR\" && while true; do
        echo \"[quickroom \$(date '+%Y-%m-%d %H:%M:%S')] Starting server on port $PORT (host 0.0.0.0)...\" >> \"$LOG_FILE\"
        \"$PYTHON_BIN\" -u \"$SERVER_SCRIPT\" $PORT 0.0.0.0 >> \"$LOG_FILE\" 2>&1
        EXIT_CODE=\$?
        echo \"[quickroom \$(date '+%Y-%m-%d %H:%M:%S')] Server process exited with code \$EXIT_CODE. Restarting in 2s...\" >> \"$LOG_FILE\"
        sleep 2
    done"

    # Wait for the server to bind to the port
    echo -n "Waiting for server to initialize..."
    for _ in {1..10}; do
        if is_port_listening; then
            break
        fi
        echo -n "."
        sleep 0.5
    done
    echo ""

    if is_port_listening; then
        echo -e "${GREEN}${BOLD}✓ QuickRoom server started successfully!${NC}"
        echo -e "Tmux session is detached and will persist permanently until server shutdown."
        print_urls
    else
        echo -e "${RED}Server did not start listening within 5 seconds.${NC}"
        echo -e "Check logs for errors: ${CYAN}./quickroom.sh logs${NC}"
    fi
}

kill_server() {
    echo -e "\n${BOLD}=== 2. Killing QuickRoom Server ===${NC}"
    local killed_any=0

    if is_tmux_running; then
        echo -e "Stopping tmux session '${CYAN}${SESSION_NAME}${NC}'..."
        tmux kill-session -t "$SESSION_NAME" 2>/dev/null
        killed_any=1
    fi

    # Release any lingering process on the port
    if is_port_listening; then
        echo -e "Terminating processes listening on port ${CYAN}${PORT}${NC}..."
        fuser -k -n tcp "$PORT" 2>/dev/null
        killed_any=1
    fi

    pkill -f "python3.*server\.py.*$PORT" 2>/dev/null && killed_any=1

    sleep 1

    if ! is_tmux_running && ! is_port_listening; then
        if [ $killed_any -eq 1 ]; then
            echo -e "${GREEN}${BOLD}✓ QuickRoom server successfully stopped.${NC}"
        else
            echo -e "${YELLOW}Server was not running.${NC}"
        fi
    else
        echo -e "${RED}Failed to completely terminate server processes. Force killing...${NC}"
        fuser -k -9 -n tcp "$PORT" 2>/dev/null
    fi
}

inspect_logs() {
    echo -e "\n${BOLD}=== 3. Inspecting Server Logs ===${NC}"
    if [ ! -f "$LOG_FILE" ]; then
        echo -e "${YELLOW}No log file found at ${LOG_FILE}.${NC}"
        return 0
    fi

    echo -e "${CYAN}--- Last 25 lines of ${LOG_FILE} ---${NC}"
    tail -n 25 "$LOG_FILE"
    echo -e "${CYAN}------------------------------------------------${NC}"
    echo ""
    echo -e "Log options:"
    echo -e "  ${BOLD}[f]${NC} Follow live logs (tail -f) - press Ctrl+C to stop"
    echo -e "  ${BOLD}[a]${NC} Attach to tmux session directly (Ctrl+B then D to detach)"
    echo -e "  ${BOLD}[Enter]${NC} Return to main menu"
    echo -n "Choose an option: "
    read -r log_choice

    case "$log_choice" in
        f|F)
            echo -e "\n${CYAN}Streaming live logs (Press Ctrl+C to return to menu)...${NC}\n"
            trap 'echo -e "\n${YELLOW}Stopped log stream.${NC}"; trap - INT; return 0' INT
            tail -n 30 -f "$LOG_FILE"
            trap - INT
            ;;
        a|A)
            if is_tmux_running; then
                echo -e "${CYAN}Attaching to tmux session '${SESSION_NAME}'...${NC}"
                echo -e "${YELLOW}Tip: Press [Ctrl+B] then [D] to detach without killing the server.${NC}"
                sleep 1
                tmux attach-session -t "$SESSION_NAME"
            else
                echo -e "${RED}Tmux session '${SESSION_NAME}' is not running.${NC}"
            fi
            ;;
        *)
            ;;
    esac
}

print_urls() {
    echo -e "\n${BOLD}Server URLs:${NC}"
    echo -e "  • Remote Host: ${CYAN}http://${HOSTNAME_VAL}:${PORT}/${NC}"
    if [ -n "$IP_VAL" ] && [ "$IP_VAL" != "$HOSTNAME_VAL" ]; then
        echo -e "  • Direct IP:   ${CYAN}http://${IP_VAL}:${PORT}/${NC}"
    fi
    echo -e "  • Localhost:   ${CYAN}http://localhost:${PORT}/${NC}"
    echo -e "  • SSH Tunnel:  ${BOLD}ssh -L ${PORT}:localhost:${PORT} $(whoami)@${HOSTNAME_VAL}${NC}"
}

open_browser() {
    echo -e "\n${BOLD}=== 4. Opening Server in Browser ===${NC}"
    if ! is_port_listening; then
        echo -e "${YELLOW}Warning: The server does not appear to be running on port ${PORT}.${NC}"
        echo -e "Start it first with option 1."
    fi

    local target_url="http://${HOSTNAME_VAL}:${PORT}/"
    local local_url="http://localhost:${PORT}/"

    print_urls

    echo -e "\nAttempting to launch default browser..."
    local opened=0

    # Try standard open commands if display or browser tool is available
    if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "$target_url" >/dev/null 2>&1 && opened=1
        fi
    fi

    if [ $opened -eq 0 ]; then
        if command -v python3 >/dev/null 2>&1; then
            python3 -m webbrowser -t "$target_url" >/dev/null 2>&1 && opened=1
        fi
    fi

    if [ $opened -eq 1 ]; then
        echo -e "${GREEN}✓ Launch command dispatched to browser.${NC}"
    else
        echo -e "${YELLOW}No active graphical display detected (running via headless SSH).${NC}"
        echo -e "Click or copy the URL above directly into your local browser!"
    fi
}

show_menu() {
    while true; do
        clear 2>/dev/null || echo -e "\n----------------------------------------\n"
        echo -e "${BOLD}${BLUE}================================================================${NC}"
        echo -e "${BOLD}${BLUE}                  U of T QuickRoom Finder CLI                   ${NC}"
        echo -e "${BOLD}${BLUE}================================================================${NC}"
        echo -e " Status: $(get_status_line)"
        echo -e " Port:   ${CYAN}${PORT}${NC} (obscure port with low collision risk)"
        echo -e " Host:   ${HOSTNAME_VAL}"
        echo -e "${BLUE}----------------------------------------------------------------${NC}"
        echo -e "  ${BOLD}1)${NC} Start the server"
        echo -e "  ${BOLD}2)${NC} Kill the server"
        echo -e "  ${BOLD}3)${NC} Inspect logs"
        echo -e "  ${BOLD}4)${NC} Open the server in the browser"
        echo -e "  ${BOLD}5)${NC} Exit"
        echo -e "${BLUE}================================================================${NC}"
        echo -n "Choose an option [1-5]: "
        read -r choice

        case "$choice" in
            1)
                start_server
                ;;
            2)
                kill_server
                ;;
            3)
                inspect_logs
                ;;
            4)
                open_browser
                ;;
            5|q|Q|exit)
                echo -e "\n${GREEN}Exiting CLI. The tmux session (if running) remains active in background.${NC}\n"
                break
                ;;
            *)
                echo -e "\n${RED}Invalid option: '$choice'. Please choose 1, 2, 3, 4, or 5.${NC}"
                ;;
        esac

        if [ "$choice" != "5" ] && [ "$choice" != "q" ] && [ "$choice" != "Q" ] && [ "$choice" != "exit" ]; then
            echo ""
            echo -n "Press [Enter] to return to menu..."
            read -r _
        fi
    done
}

# Handle direct CLI arguments
case "$1" in
    1|start)
        start_server
        ;;
    2|kill|stop)
        kill_server
        ;;
    3|logs|log|inspect)
        inspect_logs
        ;;
    4|open|browse|browser)
        open_browser
        ;;
    status)
        echo -e "QuickRoom Status: $(get_status_line)"
        ;;
    help|-h|--help)
        echo "Usage: $0 [1|start | 2|kill | 3|logs | 4|open | status]"
        echo "Run without arguments to open interactive menu."
        ;;
    "")
        show_menu
        ;;
    *)
        echo "Unknown option: $1"
        echo "Usage: $0 [1|start | 2|kill | 3|logs | 4|open | status]"
        exit 1
        ;;
esac
