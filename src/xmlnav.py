#!/usr/bin/env python3
#############################################
# script to mount a xml file
# to a directory structure
# for analysing large xml files
# Usage:
#./xmlnav.py some_xml_file.xml ./mount -f &
############################################
import sys
import re
import os
import glob
from socket import timeout
from lxml import objectify
from xml.etree import ElementTree
import lxml
from types import *
import traceback
from collections import OrderedDict
import urllib.request
import os, stat, errno
try:
    import _find_fuse_parts
except ImportError:
    pass
import fuse
from fuse import Fuse


if not hasattr(fuse, '__version__'):
    raise RuntimeError("fuse-py doesn't know fuse.__version__, maybe it's too old.")

fuse.fuse_python_api = (0, 2)

hello_str = b'Xml World!\n'

class MyStat(fuse.Stat):
    def __init__(self):
        self.st_mode = 0
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = 0
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = 0
        self.st_atime = 0
        self.st_mtime = 0
        self.st_ctime = 0

class MyDirectory:
    parent = None
    stat = None
    name = ""
    path = ""
    files = []
    dirs = []
    def __init__(self, path):
        self.files = []
        self.dirs = []
        self.stat = MyStat()
        self.stat.st_mode = stat.S_IFDIR| 0o777
        self.stat.st_nlink = 2
        self.path = path
        self.name = path 
    def add(self, object):
        if type(object) == MyFile:
            self.addFile(object)
        elif type(object) == MyDirectory:
            self.addFolder(object)
        else:
            print("Error adding")

    def hasObject(self, name ):
        for f in self.dirs:
            if f.name == name:
                return f
        return None
    
    def find(self, name ):
        if name =="." or name =="..":
            return None
        for file in self.files:
  #          print("F:",file.name, name)
            if file.name == name:
                return file
        for directory in self.dirs:
  #          print("D:",directory.name, name)
            if directory.name == name:
  #              print("found", directory.name, type(directory) )
                return directory

        #print("file", name, "not found" )
        return None
    #
    # Elements can have same name, but not directories
    # if name exists add a number to it
    def newFolderName(self, name):
        uniq = False
        pcnt = 0
        cnt = 0
        while not(uniq):
            for directory in self.dirs:
                if directory.name == name+str(cnt):
                    cnt+=1
            if pcnt == cnt:
                #print( name+str(cnt),"seems uniq")
                uniq=True
            else:
               pcnt = cnt
        return name+str(cnt)

    def addFile(self, file):
        self.files.append(file)
    def addFolder(self, folder):
        if folder == None:
            print("Non folder!")
        if self.find(folder.name):
       #     print("Folder ",folder.name,"exists, renaming")
            folder.name = self.newFolderName( folder.name )
        self.dirs.append(folder)
    def getFiles(self):
        return self.files
    def getFolders(self):
        return self.dirs

    def list(self):
        print(self.name)
        print("Files:")
        for file in self.files:
            print(" ",file.name)

        print("Dirs:")
        for directory in self.dirs:
            print(" ",directory.name)

class MyFile:
    stat = None
    name = ""
    path = ""
    content = b''
    def __init__(self,name):
        self.name = name
        self.stat = MyStat()
        self.stat.st_mode = stat.S_IFREG | 0o444
        self.stat.st_nlink = 1
    def setContent(self, content):
        self.content = content
        self.stat.st_size = len(content)
    def getContent(self):
        return self.content

class XmlFS(Fuse):
    addXmlAsFile = False
    xml = []
    tree =  None

    def scan(self, folder, name, obj ):
        raw = str(lxml.etree.tostring(obj))
        if folder == None:
            folder = MyDirectory(name)
            folder.add(MyDirectory("."))
            folder.add(MyDirectory(".."))
            folder.parent=None

    #    exists = folder.hasObject(obj.tag )
    #    print("Folder: ",obj.tag, folder.parent )
        if len(obj.attrib) > 0:
            attributes = folder.hasObject(".attrib")
            if attributes == None:
                attributes = MyDirectory(".attrib")
                attributes.add(MyDirectory("."))
                attributes.add(MyDirectory(".."))
                attributes.parent = folder
                folder.add( attributes)
            for att in obj.attrib:
                file = MyFile( att )
                file.setContent( bytes(obj.attrib[att]+"\n", 'utf-8') )
    #           print("  .attrib/", file.name)
                attributes.add( file )
        if obj.text != None:
    #        print("Element ",obj.tag," has text")
            file = MyFile( "text")
            file.setContent( bytes(obj.text+"\n", 'utf-8') )
            folder.add( file )
        # add data.xml containing the element that defined the
        # directory
        if self.addXmlAsFile:
            rawxml = MyFile( "data.xml")
            rawxml.setContent( bytes(raw, 'utf-8') )
            folder.add(rawxml)

        children = obj.getchildren()
        for f in children:
            #print(type(f))
            newfolder=self.scan(None, f.tag, f)
            newfolder.parent = folder
            folder.add( newfolder  )

        return folder

    def begin(self, file):
        with open(file, "rb") as xti:
            data = xti.read()
            self.xml = objectify.fromstring(data)
            self.tree = self.scan( None, "/", self.xml )

#        self.tree.list()

    def getattr(self, path):
        obj = self.getObject(path)
        if obj != None:
        #    print("Obj:", obj.name, "size:",obj.stat.st_size )
            return obj.stat
        #else:
        #    print("Unknown obj:",path)
        return None

    def getObject(self, path):
        if path =="/":
            return self.tree
        else:
            parts = path.split("/")[1:]
            parent = self.tree
            for p in parts:
                parent = parent.find(p)
            return parent

    def readdir(self, path, offset):
        obj = self.getObject(path)
        if obj !=None:
            if type(obj) == MyDirectory:
                for d in obj.getFolders():
                    yield fuse.Direntry(name=d.name, type=d.stat.st_mode) 
                for f in obj.getFiles():
                    yield fuse.Direntry(name=f.name, type=f.stat.st_mode) 
            else:
                yield fuse.Direntry(name=obj.name, type=obj.stat.st_mode) 
        else:
            print("Object not found")

    def open(self, path, flags):
        obj = self.getObject(path)
        if obj == None:
            print("No object", path)
            return -errno.EACCES
        
        if type(obj) == MyFile:
            accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
            if (flags & accmode) != os.O_RDONLY:
                print("Only read access allowed")
                return -errno.EACCES
        
        return 0

    def read(self, path, size, offset):
        obj = self.getObject(path)
        if obj == None:
            print("No obj")
            return -errno.ENOENT
        data = obj.getContent()

        slen = len(data)
        if offset < slen:
            if offset + size > slen:
                size = slen - offset
            buf = data[offset:offset+size]
        else:
            buf = b''

        #print("return:", buf, slen, obj.stat.st_size)
        return buf



if __name__ == '__main__':
    usage=""" Userspace xml """ + Fuse.fusage
    server = XmlFS(version="%prog " + fuse.__version__,
                     usage=usage,
                     dash_s_do='setsingle')
    # This will show the XML data for current directory
    #server.addXmlAsFile = True
    server.parse(errex=1)
    server.begin(sys.argv[1])
    server.main()

