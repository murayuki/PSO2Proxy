import struct
import io

from twisted.python import log

import data.blocks as blocks
import data.players as players
import data.clients as clients
import packetFactory
from PSOCryptoUtils import PSO2RSADecrypt, PSO2RC4, PSO2RSAEncrypt
import commands
import plugins.plugins as packet_manager
from config import myIpAddress as ipAddress
from config import blockNameMode as bNameMode
from config import noisy as verbose
import config


i0, i1, i2, i3 = ipAddress.split(".")
rsaDecrypter = PSO2RSADecrypt("keys/myKey.pem")
rsaEncryptor = PSO2RSAEncrypt("keys/SEGAKey.pem")

packetList = {}


class PacketHandler(object):
    def __init__(self, packet_type, packet_subtype):
        self.pktType = packet_type
        self.pktSubtype = packet_subtype

    def __call__(self, f):
        global packetList
        packetList[(self.pktType, self.pktSubtype)] = f


@PacketHandler(0x11, 0x0)
def login_packet(context, data):
    username = data[0x8:0x48].decode('utf-8')
    username = username.rstrip('\0')
    print("[LoginPacket] Logging player %s in..." % username)
    context.myUsername = username
    context.peer.myUsername = username
    if config.is_segaid_banned(username):
        print("[Bans] %s is banned! Disconnecting..." % username)
        context.transport.loseConnection()
        context.peer.transport.loseConnection()
        return None
    return data


@PacketHandler(0x11, 0xB)
def key_packet(context, data):
    if verbose:
        print("[KeyPacket] Decrypting RC4 key packet!")
    rsa_blob = data[0x8:0x88]
    decrypted = rsaDecrypter.decrypt(rsa_blob)
    if decrypted is None:
        print(
            "[KeyPacket] Could not decrypt RSA for client %s, Perhaps their client's key is unmodified? Hanging up." % context.transport.getPeer().host)
        context.transport.loseConnection()
        return None
    if verbose:
        print("[KeyPacket] Client %s RC4 key %s" % (
            context.transport.getPeer().host, ''.join("%02x " % b for b in bytearray(decrypted[0x10:0x20])),))
    context.c4crypto = PSO2RC4(decrypted[0x10:0x20])
    context.peer.c4crypto = PSO2RC4(decrypted[0x10:0x20])
    # Re-RSA packet
    blob = io.BytesIO()
    blob.write(data[:0x8])
    blob.write(rsaEncryptor.encrypt(decrypted))
    blob.write(data[0x88:len(data)])
    blob.flush()
    return blob.getvalue()


@PacketHandler(0x11, 0x1)
def block_info_packet(context, data):
    data = bytearray(data)
    block_port = context.peer.transport.getHost().port
    if block_port in blocks.blockList:
        block_info = blocks.blockList[block_port]
        if bNameMode == 0:
            address_string = ('%s%s:%i' % ((block_info[1])[:6], block_info[0], block_port)).encode('utf-16le')
            struct.pack_into('%is' % len(address_string), data, 0x1C, address_string)
            if len(address_string) < 0x40:
                struct.pack_into('%ix' % (0x40 - len(address_string)), data, 0x1C + len(address_string))
        elif bNameMode == 1 and ((block_info[1])[:5]) in config.blockNames:
            address_string = config.blockNames[(block_info[1])[:5]].encode('utf-16le')
            struct.pack_into('%is' % len(address_string), data, 0x1C, address_string)
            if len(address_string) < 0x40:
                struct.pack_into('%ix' % (0x40 - len(address_string)), data, 0x1C + len(address_string))
    return str(data)


@PacketHandler(0x11, 0x4f)
def team_room_info_packet(context, data):
    data = bytearray(data)
    o1, o2, o3, o4 = struct.unpack_from('BBBB', buffer(data), 0x20)
    ip_string = "%i.%i.%i.%i" % (o1, o2, o3, o4)
    port = struct.unpack_from('H', buffer(data), 0x28)[0]
    if port not in blocks.blockList:
        if verbose:
            print("[BlockPacket] Discovered a 'Team Room' block at %s:%i!" % (ip_string, port))
        blocks.blockList[port] = (ip_string, "Team Room", port)
    struct.pack_into('BBBB', data, 0x20, int(i0), int(i1), int(i2), int(i3))
    context.peer.changingBlocks = True
    return str(data)


@PacketHandler(0x11, 0x17)
def my_room_info_packet(context, data):
    data = bytearray(data)
    o1, o2, o3, o4 = struct.unpack_from('BBBB', buffer(data), 0x20)
    ip_string = "%i.%i.%i.%i" % (o1, o2, o3, o4)
    port = struct.unpack_from('H', buffer(data), 0x28)[0]
    if port not in blocks.blockList:
        if verbose:
            print("[BlockPacket] Discovered a 'My Room' block at %s:%i!" % (ip_string, port))
        blocks.blockList[port] = (ip_string, "My Room", port)
    struct.pack_into('BBBB', data, 0x20, int(i0), int(i1), int(i2), int(i3))
    context.peer.changingBlocks = True
    return str(data)


@PacketHandler(0x11, 0x14)
def block_switch_packet(context, data):
    data = bytearray(data)
    player_id = struct.unpack_from('I', buffer(data), 0x8)[0]
    if player_id in clients.connectedClients:
        client_info = clients.connectedClients[player_id]
        print("[ShipProxy] Got block change login from player %i, (SID: %s)" % (player_id, client_info.segaId))
    else:
        print("[ShipProxy] Got block change login for unknown client?! (ID: %i)" % player_id)
    context.playerId = player_id
    return str(data)


@PacketHandler(0x7, 0x0)
def chat_packet(context, data):
    player_id = struct.unpack_from('I', data, 0x8)[0]
    message = data[0x1C:].decode(
        'utf-16')  # This is technically improper. Should use the xor byte to check string length (See packetReader)
    if player_id == 0:  # Probably the wrong way to check, but check if a PSO2 client sent this packet
        message = message.rstrip('\0')
        if len(message) > 2 and message[0] == '|':
            command = (message.split(' ')[0])[1:]  # Get the first word (the command) and strip the '!''
            if command in commands.commandList:
                f = commands.commandList[command]
                f(context, message)  # Lazy...
            elif command in packet_manager.commands:
                f = packet_manager.commands[command]
                f(context, message)
            else:
                context.send_crypto_packet(
                    packetFactory.ChatPacket(context.playerId, "[Proxy] %s is not a command!" % command).build())
            return None
        return data
    if player_id in players.playerList:
        name = players.playerList[player_id][0]
    else:
        name = "ID:%i" % player_id
    log.msg("[ChatPacket] <%s> %s" % (name, message))
    return data


@PacketHandler(0x11, 0x10)
def block_list_packet(context, data):
    data = bytearray(data)
    print("[BlockList] Got block list! Updating local cache and rewriting packet...")
    # Jump to 0x28, 0x88 sep
    pos = 0x28
    while pos < len(data) and data[pos] != 0:
        name = data[pos:pos + 0x40].decode('utf-16le')
        o1, o2, o3, o4, port = struct.unpack_from('BBBBH', buffer(data), pos + 0x40)
        ip_string = "%i.%i.%i.%i" % (o1, o2, o3, o4)
        if port not in blocks.blockList:
            if verbose:
                print("[BlockList] Discovered new block %s at address %s:%i! Recording..." % (name, ip_string, port))
            blocks.blockList[port] = (ip_string, name)
        if bNameMode == 0:
            block_string = ("%s%s:%i" % (name[:6], ip_string, port)).encode('utf-16le')
            struct.pack_into('%is' % len(block_string), data, pos, block_string)
            if len(block_string) < 0x40:
                struct.pack_into('%ix' % (0x40 - len(block_string)), data, pos + len(block_string))
        elif bNameMode == 1 and name[:5] in config.blockNames:
            block_string = config.blockNames[name[:5]].encode('utf-16le')
            struct.pack_into('%is' % len(block_string), data, pos, block_string)
            if len(block_string) < 0x40:
                struct.pack_into('%ix' % (0x40 - len(block_string)), data, pos + len(block_string))
        struct.pack_into('BBBB', data, pos + 0x40, int(i0), int(i1), int(i2), int(i3))
        pos += 0x88

    return str(data)


@PacketHandler(0x11, 0x13)
def block_reply_packet(context, data):
    data = bytearray(data)
    struct.pack_into('BBBB', data, 0x14, int(i0), int(i1), int(i2), int(i3))
    if verbose:
        print("[ShipProxy] rewriting block ip address in query response.")
    context.peer.changingBlocks = True
    return str(data)


@PacketHandler(0xF, 0xD)
def player_info_packet(context, data):
    player_id = struct.unpack_from('I', data, 0x8)[0]  # TUPLESSS
    if context.peer.playerId is None:
        context.peer.playerId = player_id
    return data


@PacketHandler(0x1c, 0x1f)
def player_name_packet(context, data):
    player_id = struct.unpack_from('I', data, 0xC)[0]
    if player_id not in players.playerList:
        player_name = data[0x14:0x56].decode('utf-16').rstrip("\0")
        if verbose:
            print("[PlayerData] Found new player %s with player ID %i" % (player_name, player_id))
        players.playerList[player_id] = (player_name,)  # For now
    return data
