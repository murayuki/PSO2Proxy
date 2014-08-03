from twisted.protocols import basic
from twisted.internet import reactor

import packetFactory
import config
import data.clients
import data.players
import data.blocks


commandList = {}


class CommandHandler(object):
    def __init__(self, command_name):
        self.commandName = command_name

    def __call__(self, f):
        global commandList
        commandList[self.commandName] = f


@CommandHandler("help")
def help_command(sender, params):
    if not isinstance(sender, basic.LineReceiver):
        string = '[Command] %s, how may I help you?' % sender.transport.getPeer().host
        sender.send_crypto_packet(packetFactory.ChatPacket(sender.playerId, string).build())
    else:
        sender.transport.write("[Command] Hello Console! Valid commands: %s\n" % ', '.join(commandList.keys()))


@CommandHandler("count")
def count(sender, params):
    if not isinstance(sender, basic.LineReceiver):
        string = '[Command] There are %s users currently connected to your proxy.' % len(data.clients.connectedClients)
        sender.send_crypto_packet(packetFactory.ChatPacket(sender.playerId, string).build())
    else:
        print("[ShipProxy] There are %s users currently on the proxy." % len(data.clients.connectedClients))


@CommandHandler("reloadbans")
def reload_bans(sender, params):
    if isinstance(sender, basic.LineReceiver):
        config.load_bans()


@CommandHandler("listbans")
def list_bans(sender, params):
    if isinstance(sender, basic.LineReceiver):
        for ban in config.banList:
            print('[Bans] %s is banned.' % str(ban))
        print('[Bans] %i bans total.' % len(config.banList))


@CommandHandler("ban")
def ban(sender, params):
    if isinstance(sender, basic.LineReceiver):
        args = params.split(' ')
        if len(args) < 3:
            print("[Command] Invalid usage! Proper usage, >>> ban <segaid/pid> <value>")
            return
        if args[1] == "segaid":
            if config.is_segaid_banned(args[2]):
                print("[Command] %s is already banned!" % args[2])
                return
            config.banList.append({'segaId': args[2]})
            config.save_bans()
        elif args[1] == "pid":
            if config.is_player_id_banned(args[2]):
                print('[Command] %s is already banned!' % args[2])
                return
            config.banList.append({'playerId': args[2]})
            config.save_bans()
        else:
            print("[Command] Invalid usage! Proper usage, >>> ban <segaid/pid> <value>")
            return


@CommandHandler("kick")
def kick(sender, params):
    if isinstance(sender, basic.LineReceiver):
        args = params.split(' ')
        if len(args) < 2:
            print("[Command] Invalid usage! Proper usage: >>> kick <playerId>")
            return
        if int(args[1]) in data.clients.connectedClients:
            data.clients.connectedClients[int(args[1])].get_handle().transport.loseConnection()
            print("[Command] Kicked %s." % args[1])
        else:
            print("[Command] I couldn't find %s!" % args[1])


@CommandHandler("clients")
def list_clients(sender, params):
    if isinstance(sender, basic.LineReceiver):
        print("[ClientList] === Connected Clients (%i total) ===" % len(data.clients.connectedClients))
        for ip, client in data.clients.connectedClients.iteritems():
            client_handle = client.get_handle()
            client_host = client_handle.transport.getPeer().host
            client_segaid = client_handle.myUsername
            if client_segaid is None:
                continue
            client_segaid = client_segaid.rstrip('\0')
            client_player_id = client_handle.playerId
            if client_player_id in data.players.playerList:
                client_player_name = data.players.playerList[client_player_id][0].rstrip('\0')
            else:
                client_player_name = None
            block_number = client_handle.transport.getHost().port
            if block_number in data.blocks.blockList:
                client_block = data.blocks.blockList[block_number][1].rstrip('\0')
            else:
                client_block = None
            print("[ClientList] IP: %s SEGA ID: %s Player ID: %s Player Name: %s Block: %s" % (
            client_host, client_segaid, client_player_id, client_player_name, client_block))


@CommandHandler("globalmsg")
def global_message(sender, params):
    if isinstance(sender, basic.LineReceiver):
        if len(params.split(' ', 1)) < 2:
            print("[ShipProxy] That message is not long enough!")
            return
        message = params.split(' ', 1)[1]
        for client in data.clients.connectedClients.values():
            if client.get_handle() is not None:
                client.get_handle().send_crypto_packet(
                    packetFactory.GoldGlobalMessagePacket("[Proxy Global Message] %s" % message).build())
        print("[ShipProxy] Sent global message!")


@CommandHandler("exit")
def exit_proxy(sender, params):
    if isinstance(sender, basic.LineReceiver):
        print("[ShipProxy] Exiting...")
        reactor.callFromThread(reactor.stop)
