#include "game_price/app/command_line.h"

#include <sstream>
#include <stdexcept>

namespace game_price {
namespace {

std::string joinGameName(const std::vector<std::string>& arguments) {
    if (arguments.size() <= 1) return "Stardew Valley";

    std::ostringstream result;
    for (std::size_t index = 1; index < arguments.size(); ++index) {
        if (index > 1) result << ' ';
        result << arguments[index];
    }
    return result.str();
}

}  // namespace

CommandLineOptions parseCommandLine(const std::vector<std::string>& arguments) {
    if (arguments.empty()) return {};

    const auto& command = arguments.front();
    if (command == "--help" || command == "-h" || command == "help") {
        return CommandLineOptions{AppCommand::Help, ""};
    }

    const std::string gameName = joinGameName(arguments);
    if (command == "demo") return CommandLineOptions{AppCommand::Demo, gameName};
    if (command == "collect") return CommandLineOptions{AppCommand::Collect, gameName};
    if (command == "compare") return CommandLineOptions{AppCommand::Compare, gameName};
    if (command == "history") return CommandLineOptions{AppCommand::History, gameName};
    throw std::invalid_argument("Unknown command: " + command);
}

std::string commandLineHelp() {
    return
        "Usage: game_price_tracker [command] [game name]\n"
        "\n"
        "Commands:\n"
        "  demo      Collect, compare, and show history (default)\n"
        "  collect   Collect Store data and save it to SQLite\n"
        "  compare   Compare prices already stored in SQLite\n"
        "  history   Show price history and purchase recommendations\n"
        "  help      Show this help\n"
        "\n"
        "Default game name: Stardew Valley\n";
}

}  // namespace game_price
