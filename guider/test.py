import os
from guider import SysMgr, UtilMgr

try:
    long
except:
    long = int


class NetworkMgr(object):
    """ Manager for remote communication """

    def __init__(\
        self, mode, ip, port, blocking=True, tcp=False, anyPort=False):
        self.mode = mode
        self.ip = None
        self.port = None
        self.socket = None
        self.request = None
        self.status = None
        self.ignore = long(0)
        self.fileno = -1
        self.time = None
        self.sendSize = 32767
        self.recvSize = 32767
        self.tcp = tcp
        self.connected = False

        # get socket object #
        socket = SysMgr.getPkg('socket')

        try:
            from socket import socket, AF_INET, SOCK_DGRAM, \
                SOCK_STREAM, SOL_SOCKET, SO_REUSEADDR, SO_SNDBUF, SO_RCVBUF, \
                SOL_TCP, TCP_NODELAY, SO_RCVTIMEO, SO_SNDTIMEO
        except:
            return None

        try:
            # set socket type #
            if tcp:
                self.socket = socket(AF_INET, SOCK_STREAM)
            else:
                self.socket = socket(AF_INET, SOCK_DGRAM)

            self.fileno = self.socket.fileno()

            # increate socket buffer size to 1MB #
            self.socket.setsockopt(SOL_SOCKET, SO_SNDBUF, 1<<20)
            self.socket.setsockopt(SOL_SOCKET, SO_RCVBUF, 1<<20)

            # get buffer size #
            self.sendSize = self.socket.getsockopt(SOL_SOCKET, SO_SNDBUF)
            self.recvSize = self.socket.getsockopt(SOL_SOCKET, SO_RCVBUF)

            # set REUSEADDR #
            self.socket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)

            # set SENDTIMEOUT #
            '''
            sec = 1
            usec = long(0)
            timeval = struct.pack('ll', sec, usec)
            self.socket.setsockopt(SOL_SOCKET, SO_SNDTIMEO, timeval)
            '''

            # set NODELAY #
            '''
            self.socket.setsockopt(SOL_TCP, TCP_NODELAY, 1)
            '''

            # set IP & PORT #
            self.ip = ip
            self.port = port

            if mode == 'server':
                # IP #
                if not ip:
                    self.ip = '0.0.0.0'

                # PORT #
                if anyPort:
                    self.port = long(0)
                elif not port:
                    self.port = SysMgr.defaultPort

                # bind #
                try:
                    self.socket.bind((self.ip, self.port))
                except:
                    self.socket.bind((self.ip, self.port))

                # get bind port #
                self.port = self.socket.getsockname()[1]

            if not blocking:
                self.socket.setblocking(0)
        except:
            err = SysMgr.getErrReason()
            if err.startswith('13') and \
                not SysMgr.isRoot() and \
                port < 1024:
                feedback = ', use port bigger than 1024'
            else:
                feedback = ''

            SysMgr.printErr(\
                "Fail to create socket with %s:%s as server because %s%s" % \
                    (self.ip, self.port, err, feedback))

            '''
            if error "99 Cannot assign requested address" occurs:
                add "net.ipv4.ip_nonlocal_bind = 1" in /etc/sysctl.conf
                execute sysctl -p /etc/sysctl.conf
            '''

            self.ip = None
            self.port = None

            return None



    def listen(self, nrQueue=5):
        return self.socket.listen(nrQueue)



    def accept(self):
        return self.socket.accept()



    def bind(self, ip, port):
        return self.socket.bind((ip, port))



    def write(self, message):
        return self.send(message, write=True)



    def close(self):
        ret = self.socket.close()
        self.socket = None
        return ret



    def flush(self):
        pass



    def timeout(self, time=3):
        self.socket.settimeout(time)



    def connect(self, addr=None):
        if addr is None:
            addr = (self.ip, self.port)

        ret = self.socket.connect(addr)

        self.connected = True

        return ret



    def handleServerRequest(self, req, onlySocket=False):
        def onDownload(req):
            # parse path #
            plist = req.split('|', 1)[1]
            path = plist.split(',')
            origPath = path[0].strip()
            targetPath = path[1].strip()
            receiver = self
            targetIp = self.ip
            targetPort = self.port

            # get select object #
            selectObj = SysMgr.getPkg('select')

            # receive file #
            try:
                curSize = long(0)
                totalSize = None
                dirPos = targetPath.rfind('/')
                if dirPos >= 0 and \
                    not os.path.isdir(targetPath[:dirPos]):
                    os.makedirs(targetPath[:dirPos])

                # receive file size #
                while 1:
                    size = receiver.recv(receiver.recvSize)
                    if not size:
                        continue
                    else:
                        totalSize = long(size.decode())
                        receiver.send('ACK'.encode())
                        break

                # receive file #
                with open(targetPath, 'wb') as fd:
                    while 1:
                        selectObj.select([receiver.socket], [], [], 3)

                        buf = receiver.recv(receiver.recvSize)
                        if buf:
                            curSize += len(buf)
                            fd.write(buf)
                        else:
                            break

                        # print progress #
                        UtilMgr.printProgress(curSize, totalSize)

                UtilMgr.deleteProgress()

                SysMgr.printInfo(\
                    "%s [%s] is downloaded from %s:%s:%s successfully\n" % \
                    (targetPath, \
                    UtilMgr.convertSize2Unit(os.path.getsize(targetPath)),
                    targetIp, targetPort, origPath))
            except:
                err = SysMgr.getErrReason()
                SysMgr.printErr(\
                    'Fail to download %s from %s:%s:%s because %s' % \
                    (origPath, targetIp, targetPort, targetPath, err))
            finally:
                receiver.close()

        def onUpload(req):
            # parse path #
            plist = req.split('|', 1)[1]
            path = plist.split(',')

            origPath = path[0].strip()
            targetPath = path[1].strip()
            sender = self
            targetIp = self.ip
            targetPort = self.port
            addr = '%s:%s' % (targetIp, targetPort)

            # check file #
            if not os.path.isfile(origPath):
                SysMgr.printErr(\
                    'Failed to find %s to transfer' % origPath)
                return

            convert = UtilMgr.convertSize2Unit

            try:
                # receive file size #
                stat = os.stat(origPath)
                st_size = '%s' % stat.st_size
                sender.send(st_size)

                # read for ACK #
                while 1:
                    ret = sender.recv(3)
                    if ret is None:
                        continue
                    elif ret is False:
                        sys.exit(0)
                    else:
                        break

                # transfer file #
                curSize = long(0)
                totalSize = long(st_size)
                with open(origPath,'rb') as fd:
                    buf = fd.read(sender.sendSize)
                    while buf:
                        # print progress #
                        UtilMgr.printProgress(curSize, totalSize)

                        ret = sender.send(buf)
                        if not ret:
                            raise Exception()
                        else:
                            curSize = len(buf)

                        buf = fd.read(sender.sendSize)

                UtilMgr.deleteProgress()

                SysMgr.printInfo(\
                    "%s [%s] is uploaded to %s:%s successfully\n" % \
                        (origPath, convert(os.path.getsize(origPath)), \
                            addr, targetPath))
            except:
                err = SysMgr.getErrReason()
                SysMgr.printErr(\
                    "Fail to upload %s to %s:%s because %s" % \
                        (origPath, addr, targetPath, err))
            finally:
                sender.close()

        def onRun(req, onlySocket):
            # parse command #
            origReq = req
            command = req.split('|', 1)[1]

            # parse addr #
            addr = '%s:%s' % (self.ip, self.port)

            if not onlySocket:
                SysMgr.printInfo(\
                    "'%s' is executed from %s\n" % (command, addr))

            # return just the connected socket #
            if onlySocket:
                return self

            # get select object #
            selectObj = SysMgr.getPkg('select')

            print(oneLine)

            # run mainloop #
            isPrint = False
            while 1:
                try:
                    [readSock, writeSock, errorSock] = \
                        selectObj.select([self.socket], [], [])

                    # receive packet #
                    output = self.getData()
                    if not output:
                        break

                    print(output[:-1])
                    isPrint = True
                except:
                    break

            # print output from server #
            if not isPrint:
                print('No response')

            print(oneLine)

            # close connection #
            try:
                self.close()
            except:
                pass



        # get select object to check #
        SysMgr.getPkg('select')

        # unmarshalling #
        if type(req) is tuple:
            try:
                req = req[0].decode()
            except:
                req = req[0]

            # handle request #
            if not req:
                return

            elif req.upper().startswith('DOWNLOAD'):
                return onDownload(req)

            elif req.upper().startswith('UPLOAD'):
                return onUpload(req)

            elif req.upper().startswith('RUN'):
                return onRun(req, onlySocket)

            elif req.startswith('ERROR'):
                err = req.split('|', 1)[1]
                errMsg = err.split(':', 1)[0]
                SysMgr.printErr(errMsg)

            else:
                SysMgr.printErr(\
                    "Fail to recognize '%s' request" % req)

        elif not req:
            SysMgr.printErr(\
                "No response from server")

        else:
            SysMgr.printErr(\
                "received wrong reply '%s'" % req)



    def send(self, message, write=False):
        if self.ip is None or self.port is None:
            SysMgr.printErr(\
                "Fail to use IP address for client because it is not set")
            return False
        elif not self.socket:
            SysMgr.printErr(\
                "Fail to use socket for client because it is not set")
            return False

        # encode message #
        if UtilMgr.isString(message):
            message = UtilMgr.encodeStr(message)

        try:
            # check protocol #
            if self.tcp:
                ret = self.socket.send(message)
            elif not write and SysMgr.localServObj:
                ret = SysMgr.localServObj.socket.sendto(\
                    message, (self.ip, self.port))
            else:
                ret = self.socket.sendto(message, (self.ip, self.port))

            if ret < 0:
                raise Exception()

            if self.status != 'ALWAYS':
                self.status = 'SENT'
            return True
        except SystemExit:
            sys.exit(0)
        except:
            err = SysMgr.getErrReason()
            SysMgr.printErr(\
                "Fail to send data to %s:%d as server because %s" % \
                (self.ip, self.port, err))
            return False



    def sendto(self, message, ip, port):
        if not ip or not port:
            SysMgr.printErr(\
                "Fail to use IP address for client because it is not set")
            return False
        elif not self.socket:
            SysMgr.printErr(\
                "Fail to use socket for client because it is not set")
            return False

        # encode message #
        if UtilMgr.isString(message):
            message = UtilMgr.encodeStr(message)

        try:
            self.socket.sendto(message, (ip, port))
            return True
        except SystemExit:
            sys.exit(0)
        except:
            err = SysMgr.getErrReason()
            SysMgr.printErr(\
                "Fail to send data to %s:%d as client because %s" % \
                (self.ip, self.port, err))
            return False



    def recv(self, size=0):
        if self.ip is None or self.port is None:
            SysMgr.printErr(\
                "Fail to use IP address for server because it is not set")
            return False
        elif not self.socket:
            SysMgr.printErr(\
                "Fail to use socket for client because it is not set")
            return False

        # set recv size #
        if size == 0:
            size = self.recvSize

        try:
            return self.socket.recv(size)
        except SystemExit:
            sys.exit(0)
        except:
            err = SysMgr.getErrReason()
            SysMgr.printWarn(\
                "Fail to receive data from %s:%d as client because %s" % \
                (self.ip, self.port, err))
            return False



    def getData(self):
        try:
            data = b''

            # receive and composite packets #
            while 1:
                output = self.recvfrom(noTimeout=True)

                # handle timeout #
                if not output:
                    continue

                # get only data #
                output = output[0]

                # composite packets #
                data = data + output

                if len(output) == 0:
                    break

                # decode data #
                try:
                    output = output.decode()
                except:
                    pass

                if len(output) < self.recvSize and \
                    output[-1] == '\n':
                    break
        except SystemExit:
            sys.exit(0)
        except:
            err = SysMgr.getErrReason()
            SysMgr.printErr(\
                "Fail to get data from %s:%d as client because %s" % \
                (self.ip, self.port, err))
            return None

        # decode data #
        try:
            retstr = data.decode()
            return retstr
        except:
            return data



    def recvfrom(self, size=0, noTimeout=False, verbose=True):
        if self.ip is None or self.port is None:
            SysMgr.printErr(\
                "Fail to use IP address for server because it is not set")
            return False
        elif not self.socket:
            SysMgr.printErr(\
                "Fail to use socket for client because it is not set")
            return False

        # get socket object #
        socket = SysMgr.getPkg('socket', False)

        # set recv size #
        if size == 0:
            size = self.recvSize

        while 1:
            try:
                message, address = self.socket.recvfrom(size)
                return (message, address)
            except socket.timeout:
                if noTimeout:
                    continue
                SysMgr.printWarn(\
                    "Fail to receive data from %s:%d as client because %s" % \
                    (self.ip, self.port, 'timeout'))
                return None
            except KeyboardInterrupt:
                sys.exit(0)
            except SystemExit:
                sys.exit(0)
            except:
                if verbose:
                    SysMgr.printWarn(\
                        "Fail to receive data from %s:%d as client because %s" % \
                            (self.ip, self.port, SysMgr.getErrReason()))
                return None



    @staticmethod
    def getDataType(data):
        if not data or len(data) == 0:
            return 'None'

        data = data.lstrip()

        if data.startswith('{'):
            return 'JSON'
        elif '[Info' in data[:10] or \
            '[Error' in data[:10] or \
            '[Warning' in data[:10] or \
            '[Step' in data[:10]:
            return 'LOG'
        else:
            return 'CONSOLE'



    @staticmethod
    def requestCmd(connObj, cmd):
        if not connObj:
            return

        # send request to server #
        connObj.send(cmd)

        # receive reply from server #
        reply = connObj.recvfrom()

        # handle reply from server #
        try:
            connObj.handleServerRequest(reply)
        except:
            return



    @staticmethod
    def requestPing():
        return NetworkMgr.execRemoteCmd("PING:PING")



    @staticmethod
    def getCmdPipe(connObj, cmd):
        if not cmd:
            return None

        # add command prefix #
        if cmd.upper().startswith('PING'):
            pass
        elif not cmd.startswith('run:'):
            cmd = 'run:%s' % cmd

        # send request to server #
        connObj.send(cmd)

        # receive reply from server #
        reply = connObj.recvfrom()
        try:
            if reply and reply[0].decode() == 'PONG':
                return True
        except:
            pass

        # handle reply from server #
        try:
            return connObj.handleServerRequest(reply, onlySocket=True)
        except:
            return None



    @staticmethod
    def execRemoteCmd(command):
        # get new connection #
        connObj = NetworkMgr.getServerConn()
        if not connObj:
            return None

        # launch remote command #
        pipe = NetworkMgr.getCmdPipe(connObj, command)
        return pipe



    @staticmethod
    def getServerConn():
        def printErr():
            SysMgr.printErr(\
                "No running server or wrong server address")

        # set server address in local #
        if SysMgr.isLinux and not SysMgr.remoteServObj:
            try:
                addr = SysMgr.getProcAddrs(__module__)
            except:
                addr = None

            if not addr:
                return None

            # classify ip and port #
            service, ip, port = NetworkMgr.parseAddr(addr)
            if service == ip == port == None:
                printErr()
                return None
            else:
                NetworkMgr.setRemoteServer(addr, tcp=True)
        # set server address again #
        elif SysMgr.remoteServObj:
            servObj = SysMgr.remoteServObj
            ip = servObj.ip
            port = servObj.port
            NetworkMgr.setRemoteServer('%s:%s' % (ip, port), tcp=True)

        # check server address #
        if not SysMgr.remoteServObj:
            printErr()
            return None

        # bind local socket for UDP #
        try:
            if not SysMgr.remoteServObj.tcp and \
                SysMgr.localServObj:
                lip = SysMgr.localServObj.ip
                lport = SysMgr.localServObj.port
                SysMgr.remoteServObj.socket.bind((lip, lport))
        except:
            err = SysMgr.getErrReason()
            SysMgr.printErr(\
                "Fail to bind socket to %s:%s for connection because %s" % \
                    (lip, lport, err))

        # do connect to server #
        try:
            connObj = SysMgr.remoteServObj

            connObj.timeout()

            # connect with handling CLOSE_WAIT #
            while 1:
                try:
                    connObj.connect()
                    break
                except:
                    err = SysMgr.getErrReason()
                    SysMgr.printWarn(\
                        "Fail to connect to %s:%s because %s" % \
                            (ip, port, err))
                    if err.startswith('99'):
                        time.sleep(0.1)
                        continue
                    break

            return connObj
        except:
            err = SysMgr.getErrReason()
            SysMgr.printErr(\
                "Fail to set socket for connection because %s" % err)
            return None



    @staticmethod
    def parseAddr(value):
        service = None
        ip = None
        port = None

        if not UtilMgr.isString(value):
            return (service, ip, port)

        # get request and address #
        cmdList = value.split('@')
        if len(cmdList) >= 2:
            service = cmdList[0]
            addr = cmdList[1]
        else:
            addr = value

        # get ip and port #
        addrList = addr.split(':')
        if len(addrList) >= 2:
            try:
                if len(addrList[0]) > 0:
                    ip = addrList[0]
                if len(addrList[1]) > 0:
                    port = long(addrList[1])
            except:
                pass
        else:
            try:
                if '.' in addrList[0]:
                    ip = addrList[0]
                else:
                    port = long(addrList[0])
            except:
                pass

        return (service, ip, port)



    @staticmethod
    def setRemoteServer(value, tcp=False):
        # receive mode #
        if value and len(value) == 0:
            SysMgr.remoteServObj = 'NONE'
            return

        # request mode #
        service, ip, port = NetworkMgr.parseAddr(value)

        # set PRINT as default #
        if not service:
            service = 'PRINT'

        if not ip:
            ip = NetworkMgr.getPublicIp()

        if not port:
            port = SysMgr.defaultPort

        # check server addresses #
        if SysMgr.localServObj and \
            SysMgr.localServObj.ip == ip and \
            SysMgr.localServObj.port == port:
            SysMgr.printErr((\
                "wrong option value with -X, "
                "local address and remote address are same "
                "with %s:%s") % (ip, port))
            sys.exit(0)

        if not ip or not port or \
            not SysMgr.isEffectiveRequest(service):
            reqList = ''
            for req in ThreadAnalyzer.requestType:
                reqList += req + '|'

            SysMgr.printErr(\
                ("wrong option value with -X, "
                "input [%s]@IP:PORT as remote address") % \
                    reqList[:-1])
            sys.exit(0)

        # create a socket #
        networkObject = NetworkMgr('client', ip, port, tcp=tcp)
        if not networkObject.ip:
            sys.exit(0)
        else:
            networkObject.request = service
            SysMgr.remoteServObj = networkObject

        if tcp:
            proto = 'TCP'
        else:
            proto = 'UDP'

        SysMgr.printInfo(\
            "use %s:%d(%s) as remote address" % (ip, port, proto))



    @staticmethod
    def setRemoteNetwork(service, ip, port):
        # set default service #
        if not service:
            service = 'PRINT'

        errMsg = ("wrong value for remote server, "
            "input in the format [%s]@IP:PORT") % \
                '|'.join(ThreadAnalyzer.requestType)

        if not ip or not SysMgr.isEffectiveRequest(service):
            SysMgr.printErr(errMsg)
            sys.exit(0)

        if not port:
            port = SysMgr.defaultPort

        networkObject = NetworkMgr('client', ip, port)
        if not networkObject.ip:
            sys.exit(0)
        else:
            networkObject.status = 'ALWAYS'
            networkObject.request = service
            naddr = '%s:%s' % (ip, str(port))

            if service == 'PRINT':
                SysMgr.addrListForPrint[naddr] = networkObject
            elif service.startswith('REPORT_'):
                SysMgr.reportEnable = True
                SysMgr.addrListForReport[naddr] = networkObject
            else:
                SysMgr.printErr(errMsg)

        SysMgr.printInfo(\
            "use %s:%d as remote address to request %s" % \
                (ip, port, service))



    @staticmethod
    def setServerNetwork(\
        ip, port, force=False, blocking=False, tcp=False, anyPort=False):
        if SysMgr.localServObj and not force:
            SysMgr.printWarn(\
                "Fail to set server network because it is already set")
            return

        # get internet available IP first #
        if not ip:
            ip = NetworkMgr.getPublicIp()

        # print available IP list #
        try:
            iplist = sorted(NetworkMgr.getUsingIps())
            if len(iplist) > 0:
                SysMgr.printWarn(\
                    'available IP list [%s]' % ', '.join(iplist))
        except:
            pass

        # check server setting #
        if SysMgr.localServObj and \
            SysMgr.localServObj.socket and \
            SysMgr.localServObj.ip == ip and \
            SysMgr.localServObj.port == port:
            if blocking:
                SysMgr.localServObj.socket.setblocking(1)
            else:
                SysMgr.localServObj.socket.setblocking(0)
            return

        # create a new server setting #
        networkObject = NetworkMgr(\
            'server', ip, port, blocking, tcp, anyPort)
        if not networkObject.ip:
            SysMgr.printWarn(\
                "Fail to set server IP", True)
            return

        if tcp:
            proto = 'TCP'
        else:
            proto = 'UDP'

        SysMgr.localServObj = networkObject
        SysMgr.printInfo(\
            "use %s:%d(%s) as local address" % \
            (SysMgr.localServObj.ip, \
                SysMgr.localServObj.port, proto))

        return networkObject



    @staticmethod
    def prepareServerConn(cliAddr, servAddr):
        # set local address #
        if not cliAddr:
            NetworkMgr.setServerNetwork(None, None, anyPort=True)
        else:
            service, ip, port = NetworkMgr.parseAddr(cliAddr)

            NetworkMgr.setServerNetwork(ip, port)

        # set remote address #
        if servAddr:
            NetworkMgr.setRemoteServer(servAddr)

        # set client address #
        if SysMgr.localServObj:
            cliIp = SysMgr.localServObj.ip
            cliPort = SysMgr.localServObj.port
        else:
            cliIp = None
            cliPort = None

        # set server address #
        if SysMgr.remoteServObj.ip:
            servIp = SysMgr.remoteServObj.ip
            servPort = SysMgr.remoteServObj.port
        else:
            servIp = None
            servPort = None

        return (cliIp, cliPort), (servIp, servPort)



    @staticmethod
    def getRepMacAddr():
        dirPath = '/sys/class/net'

        try:
            devices = os.listdir(dirPath)
        except SystemExit:
            sys.exit(0)
        except:
            SysMgr.printOpenErr(dirPath)
            return

        for dev in devices:
            if dev == 'lo':
                continue

            target = '%s/%s/address' % (dirPath, dev)
            try:
                with open(target, 'r') as fd:
                    addr = fd.readline()[:-1]
                    return (dev, addr)
            except SystemExit:
                sys.exit(0)
            except:
                SysMgr.printOpenErr(target)

        return ('None', 'None')



    @staticmethod
    def getUsingIps():
        effectiveList = {}
        connPaths = \
            ['%s/net/udp' % SysMgr.procPath,\
            '%s/net/tcp' % SysMgr.procPath]

        for path in connPaths:
            try:
                with open(path, 'r') as fd:
                    ipList = fd.readlines()

                # remove title #
                ipList.pop(0)

                for line in ipList:
                    items = line.split()
                    ip = SysMgr.convertCIDR(items[1].split(':')[0])
                    effectiveList[ip] = None
            except SystemExit:
                sys.exit(0)
            except:
                SysMgr.printOpenWarn(path)

        return list(effectiveList.keys())



    @staticmethod
    def getGateways():
        gateways = {}

        ips = NetworkMgr.getRoutedIps()

        for item in ips:
            try:
                ip = item[1]
                if ip == '0.0.0.0' or \
                    ip == '127.0.0.1' or \
                    not ip.endswith('.1'):
                    continue

                gw = '%s.1' % ip[:ip.rfind('.')]
                gateways[gw] = None
            except SystemExit:
                sys.exit(0)
            except:
                pass

        return list(gateways.keys())



    @staticmethod
    def getMainIp():
        ipList = {}

        ipList = NetworkMgr.getUsingIps()

        # remove invaild ip #
        try:
            ipList.remove('0.0.0.0')
        except:
            pass

        if not ipList or len(ipList) == 0:
            return None
        elif '127.0.0.1' in ipList:
            return '127.0.0.1'
        else:
            return list(sorted(ipList, reverse=True))[0]



    @staticmethod
    def getRoutedIps():
        effectiveList = []
        routePath = '%s/net/route' % SysMgr.procPath
        try:
            with open(routePath, 'r') as fd:
                ipList = fd.readlines()

            # remove title #
            ipList.pop(0)

            for line in ipList:
                items = line.split()
                effectiveList.append(\
                    [items[0], SysMgr.convertCIDR(items[1])])

            return effectiveList
        except SystemExit:
            sys.exit(0)
        except:
            SysMgr.printOpenWarn(routePath)
            return effectiveList



    @staticmethod
    def getPublicIp():
        # get socket object #
        socket = SysMgr.getPkg('socket', False)
        if not socket:
            return

        from socket import socket, AF_INET, SOCK_DGRAM, SOCK_STREAM

        ret = None

        try:
            s = socket(AF_INET, SOCK_STREAM)
            s.settimeout(0.3)

            # connect to google public IP #
            s.connect(("8.8.8.8",53))

            ret = s.getsockname()[0]
        except SystemExit:
            sys.exit(0)
        except:
            SysMgr.printWarn("Fail to get public IP address")

        if not ret:
            ret = NetworkMgr.getMainIp()

        return ret



    def __del__(self):
        try:
            self.close()
        except:
            pass



def get_dirs(result, parent_path, level, max_level):
    file_list = os.listdir(parent_path)
    parent_abspath = "[%s]" % (os.path.abspath(parent_path))

    if len(file_list) == 0 or\
                (max_level != -1 and max_level <= level):
        return (0, 0, 0)

    total_size = long(0)
    total_file = long(0)
    total_dir = long(0)

    # sort by size #
    if SysMgr.showAll:
        file_list.sort( \
            key=lambda name: os.path.getsize( \
                '%s/%s' % (parent_path, name)), reverse=True)
    # sort by type #
    else:
        file_list.sort( \
            key=lambda f: os.path.isfile(os.path.join(parent_path, f)))

    for idx, sub_path in enumerate(file_list):

        full_path = os.path.join(parent_path, sub_path)

        if os.path.islink(full_path):
            continue

        sub_abspath = "[%s]" % (os.path.abspath(full_path))

        if os.path.isdir(full_path):
            total_dir += 1
            info = dict(sub_dirs=dict(), files=dict())
            result[parent_abspath]['sub_dirs'][sub_abspath] = info
            total_info = get_dirs(result[parent_abspath]['sub_dirs'], full_path, level + 1, max_level)

            total_size += total_info[0]
            total_dir += total_info[1]
            total_file += total_info[2]

        elif os.path.isfile(full_path):
            total_file += 1
            size = os.stat(full_path).st_size
            total_size += size

            # if not SysMgr.showAll:
            #     continue
            if 'files' not in result[parent_abspath]:
                result[parent_abspath]['files'] = dict()
            result[parent_abspath]['files'][sub_abspath] = dict(size=UtilMgr.convertSize2Unit(size), type='file')

    result[parent_abspath]['size'] = UtilMgr.convertSize2Unit(total_size)
    result[parent_abspath]['dir'] = UtilMgr.convertNumber(total_dir)
    result[parent_abspath]['file'] = UtilMgr.convertNumber(total_file)

    return (total_size, total_dir, total_file)


def test(path='.'):
    abspath = "[%s]" % (os.path.abspath(path))
    result = dict()
    result[abspath] = dict(sub_dirs=dict(), files=dict())
    get_dirs(result, path, 0, -1)
    json_result = UtilMgr.convertDict2Str(result)
    SysMgr.printPipe(json_result)


if __name__ == "__main__":
    test()