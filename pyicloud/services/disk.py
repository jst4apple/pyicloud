from datetime import datetime
import sys
from future.moves.urllib.parse import urlencode
import json
import requests
import urllib
import os
import prettytable as pt
import random
import mimetypes
import time
def randomid():
    _str = lambda l: "".join(l)
    x = ["%x"%i for i in range(16)]
    num = [x[random.randint(0,15)] for i in range(32)]
    return "-".join([_str(num[0:8]), _str(num[8:12]), _str(num[12:16]), _str(num[16:20]), _str(num[20:])] )
class DiskService(object):
    """ The 'Ubiquity' iCloud service."""

    def __init__(self, service_root, download_root,  session, params):
        self.session = session
        self.params = params
        self._root = None

        token = requests.utils.dict_from_cookiejar(session.cookies)['X-APPLE-WEBAUTH-VALIDATE']
        self.params_token = dict(params ,token = token[token.index(":t=") + 3 :-1])

        self._service_root = service_root
        self._download_root = download_root
        self.opt = {'info':'retrieveItemDetailsInFolders?', 'createfold':'createFolders?', 'remove':'moveItemsToTrash?'}
        self.opturl = lambda o:"%s/%s%s"%(self._service_root, self.opt[o], urlencode(self.params))
    def remove(self, drivewsid, etag):
        request = self.session.post(
            self.opturl('remove'),
            data = json.dumps({'items':[
                {"drivewsid":drivewsid, 'clientId':drivewsid, 'etag':etag }
                                ]}),
            headers={'Content-type': 'text/plain'}
        )

    def createFold(self, info, name):
        id = randomid()
        print("id:", id)
        data = {"destinationDrivewsId":info['drivewsid'],
                    "folders":[
                        {"clientId":id, "name": name}
                       ]
                }


        request = self.session.post(
            self.opturl('createfold'),
            data = json.dumps(data),
            headers={'Content-type': 'text/plain'}
        )
    def upload(self, info, localpath):
    #{"filename":"3b27551d18f8cdacc63aed191da6b919.jpg","type":"FILE","content_type":"image/jpeg","size":13797}
        url = '%s/ws/%s/upload/web?%s' % (self._download_root,info['zone'],
                                              urlencode(self.params_token))
        filename = os.path.basename(localpath)
        statinfo=os.stat(localpath)
        data = {
                "filename":filename,
                "type":"FILE",
                "content_type":mimetypes.guess_type(filename)[0],
                "size":os.path.getsize(localpath)
            }
        files = {'files':(filename, open(localpath, "r"))}
        #files = {'file': open(localpath, "r")}
        ress = self.session.post(url, data = json.dumps(data)).json()#, files = files)

        if len(ress) and 'url' in ress[0]:
            res = ress[0]
            print("I'm post file %s"%filename)
            response = requests.options(res['url'])
            res = requests.post(res['url'],files = files).json()
            mtime = int(statinfo.st_mtime*1000)
            data = {"data":{"signature":res['singleFile']['fileChecksum'],
    		        "wrapping_key":res['singleFile']['wrappingKey'],
	    	        "reference_signature":res['singleFile']['referenceChecksum'],
	    	        "receipt":res['singleFile']['receipt'],
                    "size":res['singleFile']['size']
	                },
	        "command":"add_file",
	        "document_id":None,
	        "path":{"starting_document_id":info['docwsid'],"path":filename},
	        "allow_conflict":True,
	        "file_flags":{"is_writable":True,"is_executable":False,"is_hidden":False},
	        "mtime":mtime,
	        "btime":mtime
             }
            print("%s"%json.dumps(data))
            url = '%s/ws/%s/update/documents?errorBreakdown=true?%s' % (self._download_root,info['zone'],
                                              urlencode(self.params_token))
            response = self.session.post(url, data = json.dumps(data))
    def download(self, info, localpath = "./"):

        url = '%s/ws/%s/download/by_id?document_id=%s&%s' % (self._download_root,
                                              info['zone'],
                                              info['docwsid'],
                                              urlencode(self.params_token))
        #urllib.urlretrieve(url, "/".join(localpath, info['name']))
        res = self.session.get(url).json()
        if 'data_token' in res:
            filepath = localpath +  info['name'] + "." +  info['extension']
            print('downto', filepath)
            urllib.request.urlretrieve(res['data_token']['url'],filepath)

    def get_file(self, drivewsid  = "FOLDER::com.apple.CloudDocs::root"):
        request = self.session.post(
            self.opturl('info'),
            data = json.dumps([{"drivewsid":drivewsid,
                                "partialData":False
                                }
                                ]),
            headers={'Content-type': 'text/plain'}
        )
        return request.json()
    def files(self):
       return DiskNode('.', self, self.get_file())
class Cache:
    def __init__(self):
        self.names = {}
        self.objs = []
    def set(self, name, Item):
        if not name in self.names:
            self.names[name] = {'id':len(self.objs) + 1,  "obj":Item}
            self.objs.append(name)
        else:
            self.names[name].update({'obj':Item})

        return self.names[name]['id']

    def get(self, name):
        if name in self.names:
            return self.names[name]['obj']
        return None

    def id2name(self, id):
        if id  <= len(self.objs) and id > 0:
            return self.objs[id - 1]
        return None

class DiskNode:

    fileid = "_FILEID"
    comm_header = ["name", fileid, "type"]
    date_header = ["dateCreate", "lastOpenTime", "dateChanged", "dateModified"]
    header = {"SHOW": comm_header + ["fileCount/size"] + date_header,
              "FOLDER": comm_header + ["fileCount"] + date_header,
              "FILE": comm_header + ["size"] + date_header}

    def __init__(self, path, service, views):
        self._cache = Cache()
        if len(views):
            view = views[0]

            if 'name' in view:
                self.view = view
                self.name = view['name']
                self.service = service
                self.path = path +  self.name
                if len(views) and 'items' in views[0]:
                    self.maps = {item['name']:item  for item in views[0]['items'] if 'drivewsid' in item and 'name' in item}
                else:
                    self.maps = {}

    def __unicode__(self):
        return self.path

    def cache(self, name, node):
        id = self._cache.set(name, node)
        self.maps[name][self.fileid] = id

    def __getitem__(self, item):
        if isinstance(item, int):
            name = self._cache.id2name(item)
            if not name:return None
        elif isinstance(item, str):
            name = item
        else:
            return None

        if name in self.maps:
            node = self._cache.get(name)
            if node: return node
            node =  DiskNode(self.path + "/", self.service,  self.service.get_file(self.maps[name]['drivewsid']))
            self.cache(name, node)
            return node
        else:
            return  None

    def remove(self, item):
        node = self.__getitem__(item)
        if node:
            self.service.remove(node.view['drivewsid'], node.view['etag'])
            del self.maps[node.view['name']]

    def upload(self, path):
        if os.path.exists(path):
            self.service.upload(self.view, path)

    def download(self, path = "./"):

        foldpath = path + os.path.dirname(self.path) + "/"
        if not os.path.exists(foldpath):
            os.makedirs(foldpath)

        if self.view['type'] == 'FOLDER':
            print("enter folder:" + self.path)
            for child in self.maps.keys():
                self.__getitem__(child).download(path)

        elif self.view['type'] == 'FILE':
            print("downloading ", self.path)
            self.service.download(self.view, foldpath)

    def createfold(self, name):
        self.service.createFold(self.view, name)

    def refresh(self):
        self._cache = Cache()

    def list(self, **kargs):
        print(self.path)
        tb = pt.PrettyTable()
        tb.field_names = self.header['SHOW']
        tb.align = 'l'
        for name, info in self.maps.items():
            head = 'SHOW'
            self.cache(name, None)
            if 'type' in info and info['type'] in self.header:
                head = info['type']
            tb.add_row([col in info and info[col] or "" for col in self.header[head]])

        #tb.get_string(sortby="Annual Rainfall", reversesort=True)
        #print(pt.get_string(fields = ["City name", "Population"]))

        print(tb.get_string(**kargs))
