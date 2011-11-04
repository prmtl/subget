#!/usr/bin/python
#-*- coding: utf-8 -*-
import getopt, sys, os, re, glob, gtk, gobject, pango, time, operator, xml.dom.minidom, gettext, locale
import pygtk, glib
from threading import Thread
from distutils.sysconfig import get_python_lib
import subgetcore # libraries

gtk.gdk.threads_init()

if sys.version_info[0] >= 3:
    import configparser
else:
    import ConfigParser as configparser

# default we will serve gui, but application will be also usable in shell, just need to use -c or --console parametr

winSubget = ""

if os.name == "nt":
    winSubget = str(os.path.dirname(sys.path[0])) 
else:
    # dbus
    import dbus

consoleMode=False

if os.path.exists(winSubget+"/usr/share/subget/plugins/"):
    pluginsDir = winSubget+"/usr/share/subget/plugins/"
elif os.path.exists("usr/share/subget/plugins/"):
    pluginsDir="usr/share/subget/plugins/"
else:
    pluginsDir="/usr/share/subget/plugins/"

action="list"
language="pl"
languages=['pl', 'en']


    ####################################
    ##### GNU Gettext translations #####
    ####################################

if os.name == "nt":
    incpath=winSubget+"/usr/share/subget/locale/"
elif os.path.isdir("usr/share/subget/locale/"):
    incpath="usr/share/subget/locale/";
else:
    incpath="/usr/share/subget/locale/";

langs = ['pl_PL', 'en_US']
lc, encoding = locale.getdefaultlocale()

if (lc):
    langs = [lc]

#print("Translations: "+incpath)
gettext.bindtextdomain('subget', incpath)

t = gettext.translation('subget', incpath, langs, fallback=True)
_ = t.gettext


    ###########################################
    ##### End of GNU Gettext translations #####
    ###########################################


def usage():
    'Shows program usage and version, lists all options'

    print(_("subget for GNU/Linux. Simple Subtitle Downloader for shell and GUI.\nUsage: subget [long GNU option] [option] first-file, second-file, ...\n\n\n --help                : this message\n --console, -c         : show results in console, not in graphical user interface\n --language, -l        : specify preffered language\n --quick, -q           : grab first result and download"))
    print("")

def exechelper(command):
    exec(command)


class SubGet:
    dialog=None
    subtitlesList=list()
    Config = dict()
    Windows = dict() # active or non-active windows
    Windows['preferences'] = False
    plugins=dict()
    pluginsList=list() # ordered list
    queueCount = 0
    locks = dict()
    locks['reorder'] = False
    disabledPlugins = list()
    versioning = None

    def doPluginsLoad(self, args):
        global pluginsDir, plugins
        debugErrors = ""

        pluginsDir = get_python_lib()+"/subgetlib/"

        # fix for python bug which returns invalid path
        if not os.path.isdir(pluginsDir):
            pluginsDir = pluginsDir.replace("/usr/lib/", "/usr/local/lib/")

        # list of disabled plugins
        pluginsDisabled = self.configGetKey('plugins', 'disabled')

        if pluginsDisabled is not False:
            self.disabledPlugins = pluginsDisabled.split(",")


        file_list = glob.glob(pluginsDir+"*.py")

        for Plugin in file_list:
            Plugin = os.path.basename(Plugin)[:-3] # cut directory and .py

            # skip the index
            if Plugin == "__init__":
                continue

            try:
                self.disabledPlugins.index(Plugin)
                self.plugins[Plugin] = 'Disabled'
                continue
            except ValueError:
                self.togglePlugin(False, Plugin, 'activate')
                pass


        # plugin execution order
        if "plugins" in self.Config:
            if "order" in self.Config['plugins']:
                order = self.Config['plugins']['order'].split(",")

                for Item in order:
                    if Item in self.plugins:
                        # Python 2.6 compatibility
                        self.pluginsList.append(Item)
            else:
                self.reorderPlugins()
        else:
            self.reorderPlugins()

        # add missing plugins
        for k in self.plugins:
            try:
                test = self.pluginsList.index(k)
            except ValueError:
                self.pluginsList.append(k)

    def reorderPlugins(self):
        """ If plugins order is empty, try to create alphabetical order """

        for Item in self.plugins:
            self.pluginsList.append(Item)



    # close the window and quit
    def delete_event(self, widget, event, data=None):
        gtk.main_quit()
        return False

    def sendCriticAlert(self, Message):
        """ Send critical error message before exiting when in X11 session """

        if os.path.isfile("/usr/bin/kdialog"):
            os.system("/usr/bin/kdialog --error \""+Message+"\"")
        elif os.path.isfile("/usr/bin/zenity"):
            os.system("/usr/bin/zenity --info --text=\""+Message+"\"")
        elif os.path.isfile("/usr/bin/xmessage"):
            os.system("/usr/bin/xmessage -nearmouse \""+Message+"\"")


    def loadConfig(self):
        """ Parsing configuration from ~/.subget/config """

        if not os.path.isdir(os.path.expanduser("~/.subget/")):
            try:
                os.mkdir(os.path.expanduser("~/.subget/"))
            except Exception:
                print("Cannot create ~/.subget directory, please check your permissions")

        configPath = os.path.expanduser("~/.subget/config")
        if not os.path.isfile(configPath):
            configPath = "/usr/share/subget/config"

        
        if os.path.isfile(configPath):
            Parser = configparser.ConfigParser()
            try:
                Parser.read(configPath)
            except Exception as e:
                print("Error parsing configuration file from "+configPath+", error: "+str(e))
                self.sendCriticAlert("Subget: Error parsing configuration file from "+configPath+", error: "+str(e))
                sys.exit(os.EX_CONFIG)

            # all configuration sections
            Sections = Parser.sections()

            for Section in Sections:
                Options = Parser.options(Section)
                self.Config[Section] = dict()

                # and configuration variables inside of sections
                for Option in Options:
                    self.Config[Section][Option] = Parser.get(Section, Option)

    def main(self):
        """ Main function, getopt etc. """

        global consoleMode, action, _

        self.LANG = _
        self._ = _

        if os.name == "nt":
            self.subgetOSPath = winSubget+"/"
        elif os.path.exists("usr/share/subget"):
            print("[debug] Developer mode")
            self.subgetOSPath = "."
        else:
            self.subgetOSPath = ""

        try:
            opts, args = getopt.getopt(sys.argv[1:], "hcqw", ["help", "console", "quick", "language=", "watch-with-subtitles"])
        except getopt.GetoptError as err:
            print(_(Error)+": "+str(err)+", "+_("Try --help for usage")+"\n\n")
            usage()
            sys.exit(2)

        for o, a in opts:
            if o in ('-h', '--help'):
                 usage()
                 exit(2)
            if o in ('-c', '--console'):
                consoleMode=True
            if o in ('-q', '--quick'):
                action="first-result"
            if o in ('-w', '--watch-with-subtitles'):
                action="watch"

        self.loadConfig()

        if consoleMode == False and not os.name == "nt":
            try:
                bus = dbus.SessionBus()
                SubgetServiceObj = bus.get_object('org.freedesktop.subget', '/org/freedesktop/subget')
                ping = SubgetServiceObj.get_dbus_method('ping', 'org.freedesktop.subget')

                if len(args) > 0:
                    addLinks = SubgetServiceObj.get_dbus_method('addLinks', 'org.freedesktop.subget')
                    addLinks(str.join('\n', args), False)
                    print("Added new files to existing list.")
                else:
                    print(_("Only one instance (graphical window) of Subget can be running at once by one user.")) # only one instance of Subget can be running at once
                sys.exit(0)
            except dbus.exceptions.DBusException as e:
                True

        self.doPluginsLoad(args)

        if consoleMode == True:
            self.shellMode(args)
        else:
            # Fast download option
            if action == "watch":
                self.watchWithSubtitles(args)
            else:
                if not os.name == "nt":
                    # run DBUS Service within GUI to serve interface for other applications/self
                    self.DBUS = subgetcore.subgetbus.SubgetService()
                    self.DBUS.subget = self

                self.graphicalMode(args)



    ########################################################
    ##### FAST DOWNLOAD, "WATCH WITH SUBTITLES" OPTION #####
    ########################################################


    def textmodeDL(self, Plugin, File):
        State = self.plugins[Plugin]

        if type(State).__name__ != "module":
            self.queueCount = (self.queueCount - 1)
            return False


        Results = self.plugins[Plugin].download_list(File)

        for Result in Results:
            if Result == False:
                self.queueCount = (self.queueCount - 1)
                return False

            for Sub in Result:
                try:
                    self.subtitlesList.append({'language': Sub['lang'], 'name': Sub['title'], 'data': Sub['data'], 'extension': Plugin, 'file': Sub['file']})
                except Exception as e:
                    print("[textModeDL] Error trying to get list of subtitles from "+Plugin+" plugin, exception details: "+str(e))

        self.queueCount = (self.queueCount - 1)



    def textmodeWait(self):
        """ Wait util jobs not done, after that sort all results and download subtitles """

        Sleept = 0.0

        while True:
            time.sleep(0.2)
            Sleept += 0.2

            if self.queueCount <= 0:
                break

            # if waited too many time
            if Sleept > 180:
                print("[textmodeWait] One of plugins cannot finish its job, cancelling.")
                return False

        self.reorderTreeview(False) # Reorder list without using GTK


        self.finishedJobs = dict()
        prefferedLanguage = self.configGetKey('watch_with_subtitles', 'preferred_language')

        # set default language to english
        if prefferedLanguage == False:
            prefferedLanguage = 'en'

        # search for matching subtitles
        for Job in self.subtitlesList:
            if not Job['data']['file'] in self.finishedJobs:
                if Job['language'].lower() == prefferedLanguage.lower():
                    self.finishedJobs[Job['data']['file']] = Job
                    current = Thread(target=self.textmodeDLSub, args=(Job,))
                    current.setDaemon(False)
                    current.start()

        # accept other langages than preffered
        if not self.configGetKey('watch_with_subtitles', 'only_preferred_language') == "True":
            for Job in self.subtitlesList:
                if not Job['data']['file'] in self.finishedJobs:
                    self.finishedJobs[Job['data']['file']] = Job
                    current = Thread(target=self.textmodeDLSub, args=(Job,))
                    current.setDaemon(False)
                    current.start()

    def textmodeDLSub(self, Job):
        print("Downloading to "+Job['data']['file']+".txt")
        return self.plugins[Job['extension']].download_by_data(Job['data'], Job['data']['file']+".txt")


    def watchWithSubtitles(self, args):
        """ Download first matching subtitles and launch video player.
            Always returns True
        """

        if len(args) == 0:
            print("No files specified.")

        # subtitlesList
        self.queueCount = len(self.pluginsList)

        for Plugin in self.pluginsList:
            current = Thread(target=self.textmodeDL, args=(Plugin,args))
            current.setDaemon(False)
            current.start()

        # Loop waiting for download to be done
        current = Thread(target=self.textmodeWait)
        current.setDaemon(False)
        current.start()

        # wait for threads to end jobs
        current.join()

        if len(args) == 1:
            # get the first job using "for" and "break" after first result
            if not self.configGetKey('watch_with_subtitles', 'download_only') == True:
                Found = False

                for File in self.finishedJobs:
                    subgetcore.videoplayers.Spawn(self, File, File+".txt")

                    Found = True
                    break

                if Found == False:
                    self.sendCriticAlert("No subtitles found for file "+args[0])

        return True


    #################################################
    ##### END OF "WATCH WITH SUBTITLES" OPTION  #####
    #################################################





    def addSubtitlesRow(self, language, release_name, server, download_data, extension, File,Append=True):
            """ Adds parsed subtitles to list """
            
            self.subtitlesList.append({'language': language, 'name': release_name, 'server': server, 'data': download_data, 'extension': extension, 'file': File})

            pixbuf_path = self.subgetOSPath+'/usr/share/subget/icons/'+language+'.xpm'

            if not os.path.isfile(pixbuf_path):
                pixbuf_path = self.subgetOSPath+'/usr/share/subget/icons/unknown.xpm'
                print("[addSubtitlesRow] "+language+".xpm "+_("icon does not exists, using unknown.xpm"))

            try:
                pixbuf = gtk.gdk.pixbuf_new_from_file(pixbuf_path)
            except Exception:
                print(pixbuf_path+" icon file not found")
                True

            self.liststore.append([pixbuf, str(release_name), str(server), (len(self.subtitlesList)-1)])

    def reorderTreeview(self, useGTK=True):
        """ Sorting subtitles list by plugin priority """

        if self.locks['reorder'] == True:
            return False

        self.locks['reorder'] = True

        if "plugins" in self.Config:
            if self.dictGetKey(self.Config['plugins'], 'list_ordering') == False:
                print("Sorting disabled.")
                return True

        while not self.queueCount == 0:
            time.sleep(0.2) # give some time to finish the jobs
            #print("SLEEPING 200ms sec, becasue count is "+str(self.queueCount))

            if self.queueCount == 0:
                break

        #print("QUEUE COUNT: "+str(self.queueCount))

        if self.queueCount == 0:
            newList = list()

            for Item in self.subtitlesList:
                Item['priority'] = self.pluginsList.index(str(Item['extension']))
                newList.append(Item)

            sortedList = sorted(newList, key=lambda k: k['priority'])
            self.subtitlesList = list()

            if useGTK == True:
                self.liststore.clear()

                for Item in sortedList:
                    self.addSubtitlesRow(Item['language'], Item['name'], Item['server'], Item['data'], Item['extension'], Item['file'])
            else:
                for Item in sortedList:
                    self.subtitlesList.append({'language': Item['language'], 'name': Item['name'], 'server': Item['extension'], 'data': Item['data'], 'extension': Item['extension'], 'file': Item['file']})

        self.locks['reorder'] = False
        


    # UPDATE THE TREEVIEW LIST
    def TreeViewUpdate(self):
            """ Refresh TreeView, run all plugins to parse files """

            if len(self.files) == 0:
                return

            # increase queue
            self.queueCount = (self.queueCount + len(self.pluginsList))

            for Plugin in self.pluginsList:
                current = Thread(target=self.GTKCheckForSubtitles, args=(Plugin,))
                current.setDaemon(True)
                current.start()

            current = Thread(target=self.reorderTreeview)
            current.setDaemon(True)
            current.start()
            #    current = SubtitleThread(Plugin, self)
            #    current.setDaemon(True)
            #    subThreads.append(current)
            #    current.start()

            #for sThread in subThreads:
            #    sThread.join()
            #self.sObject.GTKCheckForSubtitles(self.Plugin)   


    def GTKCheckForSubtitles(self, Plugin):
            State = self.plugins[Plugin]

            if type(State).__name__ != "module":
                self.queueCount = (self.queueCount - 1)
                return

            Results = self.plugins[Plugin].language = language
            Results = self.plugins[Plugin].download_list(self.files)

            if Results == None:
                print("[plugin:"+Plugin+"] "+_("ERROR: Cannot import"))
            else:
                for Result in Results:
                    if Result == False:
                        self.queueCount = (self.queueCount - 1)
                        return False

                    for Movie in Result:
                        try:
                            if Movie.has_key("title"):
                                self.addSubtitlesRow(Movie['lang'], Movie['title'], Movie['domain'], Movie['data'], Plugin, Movie['file'])
                                print("[plugin:"+Plugin+"] "+_("found subtitles")+" - "+Movie['title'])
                        except AttributeError:
                             print("[plugin:"+Plugin+"] "+_("no any subtitles found"))

            # mark job as done
            self.queueCount = (self.queueCount - 1)
                
            
    def dictGetKey(self, Array, Key):
        """ Return key from dictionary, if not exists returns false """

        if Key in Array:
            if Array[Key] == "False":
                return False

            return Array[Key]
        else:
            return False


    # displaying the flag
    def cell_pixbuf_func(self, celllayout, cell, model, iter):
            """ Flag rendering """
            cell.set_property('pixbuf', model.get_value(iter, 0))

    def gtkDebugDialog(self,message):
            self.dialog = gtk.MessageDialog(parent = None,flags = gtk.DIALOG_DESTROY_WITH_PARENT,type = gtk.MESSAGE_INFO,buttons = gtk.BUTTONS_OK,message_format = message)
            self.dialog.set_title("Debug informations")
            self.dialog.connect('response', lambda dialog, response: self.destroyDialog())
            self.dialog.show()


    # DOWNLOAD DIALOG
    def GTKDownloadSubtitles(self):
            """ Dialog with file name chooser to save subtitles to """
            #print "TEST: CLICKED, LETS GO DOWNLOAD!"

            entry1,entry2 = self.treeview.get_selection().get_selected()    

            if entry2 == None:
                if self.dialog != None:
                    return
                else:
                    self.dialog = gtk.MessageDialog(parent = None,flags = gtk.DIALOG_DESTROY_WITH_PARENT,type = gtk.MESSAGE_INFO,buttons = gtk.BUTTONS_OK,message_format = _("No subtitles selected."))
                    self.dialog.set_title(_("Information"))
                    self.dialog.connect('response', lambda dialog, response: self.destroyDialog())
                    self.dialog.show()
            else:
                SelectID = int(entry1.get_value(entry2, 3))
                
                if len(self.subtitlesList) == int(SelectID) or len(self.subtitlesList) > int(SelectID):
                    chooser = gtk.FileChooserDialog(title=_("Where to save the subtitles?"),action=gtk.FILE_CHOOSER_ACTION_SAVE,buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_SAVE,gtk.RESPONSE_OK))
                    chooser.set_current_folder(os.path.dirname(self.subtitlesList[SelectID]['file']))
                    chooser.set_current_name(os.path.basename(self.subtitlesList[SelectID]['file'])+".txt")
                    response = chooser.run()

                    if response == gtk.RESPONSE_OK:
                        fileName = chooser.get_filename()
                        chooser.destroy()
                        self.GTKDownloadDialog(SelectID, fileName)
                    else:
                        chooser.destroy()
                else:
                    print("[GTK:DownloadSubtitles] subtitle_ID="+str(SelectID)+" "+_("not found in a list, its wired"))

    def GTKDownloadDialog(self, SelectID, filename):
             """Download progress dialog, downloading and saving subtitles to file"""

             Plugin = self.subtitlesList[SelectID]['extension']
             State = self.plugins[Plugin]

             if type(State).__name__ == "module":

                 w = gtk.Window(gtk.WINDOW_TOPLEVEL)
                 w.set_resizable(False)
                 w.set_title(_("Download subtitles"))
                 w.set_border_width(0)
                 w.set_size_request(300, 70)

                 fixed = gtk.Fixed()

                 # progress bar
                 self.pbar = gtk.ProgressBar()
                 self.pbar.set_size_request(180, 15)
                 self.pbar.set_pulse_step(0.01)
                 self.pbar.pulse()
                 w.timeout_handler_id = gtk.timeout_add(20, self.update_progress_bar)
                 self.pbar.show()

                 # label
                 label = gtk.Label(_("Please wait, downloading subtitles..."))
                 fixed.put(label, 50,5)
                 fixed.put(self.pbar, 50,30)

                 w.add(fixed)
                 w.show_all()

                 Results = self.plugins[Plugin].language = language
                 Results = self.plugins[Plugin].download_by_data(self.subtitlesList[SelectID]['data'], filename)

                 if self.VideoPlayer.get_active() == True:
                    VideoFile = self.dictGetKey(self.subtitlesList[SelectID]['data'], 'file')

                    if not VideoFile == False:
                        subgetcore.videoplayers.Spawn(self, VideoFile, filename)

                 w.destroy()

    def update_progress_bar(self):
            """ Progressbar updater, called asynchronously """
            self.pbar.pulse()
            return True


        # DESTROY THE DIALOG
    def destroyDialog(self):
            """ Destroys all dialogs and popups """
            self.dialog.destroy()
            self.dialog = None

    def gtkSelectVideo(self, arg):
            """ Selecting multiple videos to search for subtitles """
            chooser = gtk.FileChooserDialog(title=_("Please select video files"),action=gtk.FILE_CHOOSER_ACTION_OPEN,buttons=(gtk.STOCK_CANCEL,gtk.RESPONSE_CANCEL,gtk.STOCK_OPEN,gtk.RESPONSE_OK))
            chooser.set_select_multiple(True)
            response = chooser.run()

            if response == gtk.RESPONSE_OK:
                fileNames = chooser.get_filenames()
                chooser.destroy()

                for fileName in fileNames:
                    if not os.path.isfile(fileName) or not os.access(fileName, os.R_OK):
                        continue

                    self.files = list()
                    self.files.append(fileName)
                    #self.files = {fileName} # works on Python 2.7 only
                    #print self.files
                    self.TreeViewUpdate()
            else:
                chooser.destroy()

            return True

    def togglePlugin(self, x, Plugin, Action, liststore=None):
        if Action == 'activate':
            # load the plugin
            try:
                exec("import subgetlib."+Plugin)
                exec("self.plugins[\""+Plugin+"\"] = subgetlib."+Plugin)
                self.plugins[Plugin].loadSubgetObject(self)
                self.plugins[Plugin].subgetcore = subgetcore

                # refresh the list
                if not liststore == None:
                    liststore.clear() 
                    self.pluginsListing(liststore)

                return True

            except Exception as errno:
                self.plugins[Plugin] = str(errno)
                print(_("ERROR: Cannot import")+" "+Plugin+" ("+str(errno)+")")
                return False

        elif Action == 'deactivate':
            self.plugins[Plugin] = 'Disabled'

            # refresh the list
            if not liststore == None:
                liststore.clear() 
                self.pluginsListing(liststore)

            return True

    def pluginInfo(self, x, Plugin):
        print("Feature not implemented.")

    def pluginTreeviewEvent(self, treeview, event, liststore):
        menu = gtk.Menu() 

        if event.button == 3:
            x = int(event.x)
            y = int(event.y)
            time = event.time

            pthinfo = treeview.get_path_at_pos(x, y)

            if pthinfo is not None:
                path, col, cellx, celly = pthinfo
                treeview.grab_focus()
                treeview.set_cursor( path, col, 0)

                # items
                Info = None

                Plugin = liststore[pthinfo[0][0]][1]
                if self.plugins[Plugin] == 'Disabled':
                    Deactivate = gtk.MenuItem(_("Activate plugin"))
                    Deactivate.connect("activate", self.togglePlugin, Plugin, 'activate', liststore)
                else:
                    #Info = gtk.MenuItem('Informacje')
                    #Info.connect("activate", self.pluginInfo, Plugin)
                    Deactivate = gtk.MenuItem(_("Deactivate plugin"))
                    Deactivate.connect("activate", self.togglePlugin, Plugin, 'deactivate', liststore)

                #if not Info == None:
                #    menu.append(Info)

                menu.append(Deactivate)
                menu.show_all()
                menu.popup( None, None, None, event.button, time)

            return True

    def pluginsListing(self, liststore):
            for Plugin in self.pluginsList:
                try:
                    API = self.plugins[Plugin].PluginInfo['API']
                except Exception:
                    API = "?"

                try:
                    Author = self.plugins[Plugin].PluginInfo['Authors']
                except Exception:
                    Author = _("Unknown")

                try:
                    OS = self.plugins[Plugin].PluginInfo['Requirements']['OS']

                    if OS == "All":
                        OS = "Unix, Linux, Windows"

                except Exception:
                    OS = _("Unknown")

                try:
                    Packages = self.plugins[Plugin].PluginInfo['Requirements']['Packages']

                    if len(Packages) > 0:
                        i=0
                        for Package in Packages:
                            if i == 0:
                                Packages_c = Packages_c + Package
                            else:
                                Packages_c = Packages_c + Package + ", "
                            i=i+1

                except Exception:
                    Packages = _("Unknown")

                if type(self.plugins[Plugin]).__name__ == "module":
                    pixbuf = gtk.gdk.pixbuf_new_from_file(self.subgetOSPath+'/usr/share/subget/icons/plugin.png') 
                    liststore.append([pixbuf, Plugin, OS, str(Author), str(API)])
                elif self.plugins[Plugin] == "Disabled":
                    pixbuf = gtk.gdk.pixbuf_new_from_file(self.subgetOSPath+'/usr/share/subget/icons/plugin-disabled.png')
                    liststore.append([pixbuf, Plugin, OS, str(Author), str(API)])
                else:
                    pixbuf = gtk.gdk.pixbuf_new_from_file(self.subgetOSPath+'/usr/share/subget/icons/error.png') 
                    liststore.append([pixbuf, Plugin, OS, str(Author), str(API)])


    def gtkPluginMenu(self, arg):
            """ GTK Widget with list of plugins """

            if self.dictGetKey(self.Windows, 'gtkPluginMenu') == False:
                self.Windows['gtkPluginMenu'] = True
            else:
                return False

            window = gtk.Window(gtk.WINDOW_TOPLEVEL)
            window.set_title(_("Plugins"))
            window.set_resizable(False)
            window.set_size_request(700, 290)
            window.set_icon_from_file(self.subgetOSPath+"/usr/share/subget/icons/plugin.png")
            window.connect("delete_event", self.closeWindow, window, 'gtkPluginMenu')
            fixed = gtk.Fixed()

            liststore = gtk.ListStore(gtk.gdk.Pixbuf, str, str, str, str)
            treeview = gtk.TreeView(liststore)


            # column list
            tvcolumn = gtk.TreeViewColumn(_("Plugin"))
            tvcolumn1 = gtk.TreeViewColumn(_("Operating system"))
            tvcolumn2 = gtk.TreeViewColumn(_("Authors"))
            tvcolumn3 = gtk.TreeViewColumn(_("API interface version"))

            treeview.append_column(tvcolumn)
            treeview.append_column(tvcolumn1)
            treeview.append_column(tvcolumn2)
            treeview.append_column(tvcolumn3)
            treeview.set_reorderable(1)

            cellpb = gtk.CellRendererPixbuf()
            cell = gtk.CellRendererText()
            cell1 = gtk.CellRendererText()
            cell2 = gtk.CellRendererText()
            cell3 = gtk.CellRendererText()

            # add the cells to the columns - 2 in the first
            tvcolumn.pack_start(cellpb, False)
            tvcolumn.set_cell_data_func(cellpb, self.cell_pixbuf_func)
            tvcolumn.pack_start(cell, True)
            tvcolumn1.pack_start(cell1, True)
            tvcolumn2.pack_start(cell2, True)
            tvcolumn3.pack_start(cell3, True)
            tvcolumn.set_attributes(cell, text=1)
            tvcolumn1.set_attributes(cell1, text=2)
            tvcolumn2.set_attributes(cell2, text=3)
            tvcolumn3.set_attributes(cell3, text=4)

            self.pluginsListing(liststore)

            # make treeview searchable
            treeview.set_search_column(1)

            # context menu
            treeview.connect("button-press-event", self.pluginTreeviewEvent, liststore)

            # Allow sorting on the column
            if not self.configGetKey('interface', 'custom_plugins_sorting') == False:
                tvcolumn.set_sort_column_id(1)
                tvcolumn1.set_sort_column_id(1)
                tvcolumn2.set_sort_column_id(2)
                tvcolumn3.set_sort_column_id(3)

            scrolled_window = gtk.ScrolledWindow()
            scrolled_window.set_border_width(0)
            scrolled_window.set_size_request(700, 230)
            scrolled_window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_ALWAYS)
            scrolled_window.add_with_viewport(treeview)

            # Cancel button
            CancelButton = gtk.Button(stock=gtk.STOCK_CLOSE)
            CancelButton.set_size_request(90, 40)
            CancelButton.connect('clicked', self.closePluginsMenu, liststore, window)
            fixed.put(CancelButton, 600, 240) # put on fixed

            fixed.put(scrolled_window, 0, 0)
            window.add(fixed)
            window.show_all()


    def closePluginsMenu(self, x, liststore, window):
            Order = ""
            self.pluginsList = list() # clear the list

            # create new plugins list
            for Item in liststore:
                self.pluginsList.append(str(Item[1])) # add sorted elements
                Order += str(Item[1])+","

            if not "plugins" in self.Config:
                self.Config['plugins'] = dict()

            # add to configuration
            self.Config['plugins']['order'] = Order[0:-1]
            
            # save disabled items
            Disabled = ""

            for Item in self.plugins:
                if self.plugins[Item] == 'Disabled':
                    Disabled += str(Item)+","

            self.Config['plugins']['disabled'] = Disabled[0:-1]

            # save configuration and close the window
            self.saveConfiguration()
            self.closeWindow(False, False, window, 'gtkPluginMenu')
            self.reorderTreeview()

    def gtkAboutMenu(self, arg):
            """ Shows about dialog """

            if self.dictGetKey(self.Windows, 'gtkAboutMenu') == False:
                self.Windows['gtkAboutMenu'] = True
            else:
                return False

            about = gtk.Window(gtk.WINDOW_TOPLEVEL)
            about.set_title(_("About Subget"))
            about.set_resizable(False)
            about.set_size_request(600,550)
            about.set_icon_from_file(self.subgetOSPath+"/usr/share/subget/icons/Subget-logo.png")
            about.connect("delete_event", self.closeWindow, about, 'gtkAboutMenu')

            # container
            fixed = gtk.Fixed()
            
            # logo
            logo = gtk.Image()
            logo.set_from_file(self.subgetOSPath+"/usr/share/subget/icons/Subget-logo.png")
            fixed.put(logo, 12, 20)

            # title
            title = gtk.Label(_("About Subget"))
            title.modify_font(pango.FontDescription("sans 18"))
            fixed.put(title, 150, 20)

            # description title
            description = gtk.Label(_("Small, multiplatform and portable Subtitles downloader \nwritten in Python and GTK.\nWorks on most Unix systems, based on Linux kernel and on Windows NT.\nThis program is a free software licensed on GNU General Public License v3."))
            description.modify_font(pango.FontDescription("sans 8"))
            fixed.put(description, 150, 60)

            # TABS
            notebook = gtk.Notebook()
            notebook.set_tab_pos(gtk.POS_TOP)
            notebook.show_tabs = True
            notebook.set_size_request(580, 370)
            notebook.set_border_width(0) 
            self.gtkAddTab(notebook, _("Team"), _("Programming")+":\n WebNuLL <http://webnull.kablownia.org>\n\n"+_("Testing")+":\n Tiritto <http://dawid-niedzwiedzki.pl>\n WebNuLL <http://webnull.kablownia.org>\n\n"+_("Special thanks")+":\n iluzion <http://dobreprogramy.pl/iluzion>\n famfamfam <http://famfamfam.com>")

            self.gtkAddTab(notebook, _("License"), _("This program was published on Free and Open Software license.\n\nConditions:\n - You have right to share this program in original or modified form\n - You are free to run this program in any purpose\n - You are free to view and modify the source code in any purpose\n - You have right to translate this program to any language you want\n - You must leave a note about original author when modifying or sharing this software\n - The program must remain on the same license when editing or sharing\n\n\nProgram license: GNU General Public License 3 (GNU GPLv3)"))

            self.gtkAddTab(notebook, _("Translating"), "English:\n WebNuLL <http://webnull.kablownia.org>\n\nPolski:\n WebNuLL <http://webnull.kablownia.org>")


            if not os.path.isfile("/usr/share/subget/version.xml"):
                self.gtkAddTab(notebook, _("Version"), _("Version information can't be read because file /usr/share/subget/version.xml is missing."))
            else:
                if self.versioning == None:
                    try:
                        dom = xml.dom.minidom.parse("/usr/share/subget/version.xml")

                        self.versioning = {'version': dom.getElementsByTagName('version')[0].childNodes[0].data, 'platforms': '', 'mirrors': '', 'developers': '', 'contact': ''}

                        # Platforms list
                        Platforms = dom.getElementsByTagName('platform')

                        for Item in Platforms:
                            self.versioning['platforms'] += "- "+Item.childNodes[0].data+"\n"
                        del(Platforms)

                        # Mirrors list
                        Mirrors = dom.getElementsByTagName('mirror')

                        for Item in Mirrors:
                            self.versioning['mirrors'] += Item.childNodes[0].data+"\n"
                        del(Mirrors)

                        # Developers list
                        Developers = dom.getElementsByTagName('developer')

                        for Item in Developers:
                            self.versioning['developers'] += '- '+Item.childNodes[0].data+"\n"
                        del(Developers)

                        # Contact list
                        Contact = dom.getElementsByTagName('contact_im')

                        for Item in Contact:
                            self.versioning['contact'] += "* "+Item.getAttribute('type')+": "+Item.childNodes[0].data+"\n"
                        del(Contact)
                    except Exception as e:
                        self.versioning = False
                        print("Catched an exception while tried to parse /usr/share/subget/version.xml, details: "+str(e))
                    

                if self.versioning == False or self.versioning == None:
                    self.gtkAddTab(notebook, _("Version"), _("Version information can't be read because there was a problem parsing file /usr/share/subget/version.xml"))
                else:
                    self.gtkAddTab(notebook, _("Version"), _("Version")+": "+self.versioning['version']+"\n\n"+_("Supported platforms")+":\n"+self.versioning['platforms']+"\n"+_("Project developers")+":\n "+self.versioning['developers']+"\n"+_("Contact")+":\n"+self.versioning['contact'])

            fixed.put(notebook, 12, 160)

           

            # add container show all
            about.add(fixed)
            about.show_all()

    def gtkAddTab(self, notebook, label, text):
            authorsFrame = gtk.Frame("")
            authorsFrame.set_border_width(0) 
            authorsFrame.set_size_request(100, 75)
            authorsFrame.set_shadow_type(gtk.SHADOW_ETCHED_OUT)

            authorsFrameContent = gtk.Label(text)
            authorsFrameContent.set_alignment (0, 0)

            # Scrollbars
            scrolled_window = gtk.ScrolledWindow()
            scrolled_window.set_border_width(0)
            scrolled_window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
            scrolled_window.add_with_viewport(authorsFrameContent)

            authorsFrame.add(scrolled_window)

            authorsLabel = gtk.Label(label)
            notebook.prepend_page(authorsFrame, authorsLabel)

    def closeWindow(self, Event, X, Window, ID):
        Window.destroy()
        self.Windows[ID] = False

    def gtkSearchMenu(self, arg):
            if self.dictGetKey(self.Windows, 'gtkSearchMenu') == False:
                self.Windows['gtkSearchMenu'] = True
            else:
                return False

            self.sm = gtk.Window(gtk.WINDOW_TOPLEVEL)
            self.sm.set_title(_("Search"))
            self.sm.set_size_request(350, 180)
            self.sm.set_resizable(False)
            self.sm.set_icon_from_file(self.subgetOSPath+"/usr/share/subget/icons/Subget-logo.png")
            self.sm.connect("delete_event", self.closeWindow, self.sm, 'gtkSearchMenu')

            self.sm.fixed = gtk.Fixed()

            # informations
            self.sm.label = gtk.Label(_("Select website to search subtitles on.\nNote: not all websites supports searching subtitles by keywords."))

            # text query
            self.sm.entry = gtk.Entry()
            self.sm.entry.set_max_length(50)
            self.sm.entry.set_size_request(190, 26)
            self.sm.entry.show()

            # combo box with plugin selection
            self.sm.cb = gtk.combo_box_new_text()
            self.sm.cb.append_text(_("All"))
            self.sm.plugins = dict()

            for Plugin in self.pluginsList:
                if type(self.plugins[Plugin]).__name__ != "module":
                    continue

                # does plugin inform about its domain?
                if self.plugins[Plugin].PluginInfo.has_key('domain'):
                    pluginDomain = self.plugins[Plugin].PluginInfo['domain']
                    self.sm.plugins[pluginDomain] = Plugin
                    self.sm.cb.append_text(pluginDomain)
                else:
                    self.sm.plugins[Plugin] = Plugin
                    self.sm.cb.append_text(Plugin)

            # Set "All plugins" as default active
            self.sm.cb.set_active(0)


            # search button
            self.sm.searchButton = gtk.Button(_("Search"))
            self.sm.searchButton.set_size_request(80, 35)

            image = gtk.Image() # image for button
            image.set_from_stock(gtk.STOCK_FIND, 4)
            self.sm.searchButton.set_image(image)
            self.sm.searchButton.connect('clicked', self.gtkDoSearch)

            # cancel button
            self.sm.cancelButton = gtk.Button(_("Cancel"))
            self.sm.cancelButton.set_size_request(80, 35)
            self.sm.cancelButton.connect('clicked', self.closeWindow, False, self.sm, 'gtkSearchMenu')

            image = gtk.Image() # image for button
            image.set_from_stock(gtk.STOCK_CLOSE, 4)
            self.sm.cancelButton.set_image(image)

            # list clearing check box
            self.sm.clearCB = gtk.CheckButton(_("Clear list before search"))

            self.sm.fixed.put(self.sm.label, 10, 8)
            self.sm.fixed.put(self.sm.entry, 10, 60)
            self.sm.fixed.put(self.sm.cb, 210, 59)
            self.sm.fixed.put(self.sm.clearCB, 20, 90)
            self.sm.fixed.put(self.sm.searchButton, 250, 128)
            self.sm.fixed.put(self.sm.cancelButton, 165, 128)

            self.sm.add(self.sm.fixed)
            self.sm.show_all()
            return True

    def cleanUpResults(self):
        self.liststore.clear()
        self.subtitlesList = list()

    def gtkDoSearch(self, arg):
            query = self.sm.entry.get_text()
            #self.sm.destroy()
            time.sleep(0.1)

            if query == "" or query == None:
                return

            if self.sm.clearCB.get_active():
                self.cleanUpResults()

            plugin = self.sm.cb.get_active_text()

            # search in all plugins
            if plugin == _("All"):
                for Plugin in self.pluginsList:
                    try:
                        self.plugins[Plugin].language = language
                        Results = self.plugins[Plugin].search_by_keywords(query) # query the plugin for results

                        if Results == None or Results == False:
                            return

                        for Subtitles in Results:
                            if str(type(Subtitles).__name__) == "str":
                                continue

                            self.addSubtitlesRow(Subtitles['lang'], Subtitles['title'], Subtitles['domain'], Subtitles['data'], Plugin, Subtitles['file'])

                    except AttributeError:
                       True # Plugin does not support searching by keywords
            else:
                try:
                    self.plugins[self.sm.plugins[plugin]].language = language
                    Results = self.plugins[self.sm.plugins[plugin]].search_by_keywords(query) # query the plugin for results

                    if Results == None:
                        return

                    for Result in Results:
                        if str(type(Result).__name__) == "str":
                            continue

                        self.addSubtitlesRow(Result['lang'], Result['title'], Result['domain'], Result['data'], plugin, Result['file'])

                except AttributeError as errno:
                    print("[plugin:"+self.sm.plugins[plugin]+"] "+_("Searching by keywords is not supported by this plugin"))
                    True # Plugin does not support searching by keywords
    def gtkPreferencesQuit(self):
        self.winPreferences.destroy()
        self.Windows['preferences'] = False
        self.saveConfiguration()
        

    def saveConfiguration(self):
        Output = ""

        # saving settings to file
        for Section in self.Config:
            Output += "["+str(Section)+"]\n"

            for Option in self.Config[Section]:
                Output += str(Option)+" = "+str(self.Config[Section][Option])+"\n"

            Output += "\n"

        try:
            print(_("Saving to")+" ~/.subget/config")
            Handler = open(os.path.expanduser("~/.subget/config"), "wb")
            Handler.write(Output)
            Handler.close()
        except Exception as e:
            print(_("Contact")+" ~/.subget/config, "+_("Watch with subtitles")+": "+str(e))

    def gtkPreferences(self, aid):
        #self.sendCriticAlert("Sorry, this feature is not implemented yet.")
        #return
        if self.Windows['preferences'] == True:
            return False

        self.Windows['preferences'] = True

        self.winPreferences = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.winPreferences.set_title(_("Settings"))
        self.winPreferences.set_resizable(False)
        self.winPreferences.set_size_request(600, 400)
        self.winPreferences.set_icon_from_file(self.subgetOSPath+"/usr/share/subget/icons/Subget-logo.png")
        self.winPreferences.connect('delete_event', lambda b: self.gtkPreferencesQuit())

        # Container
        self.winPreferences.fixed = gtk.Fixed()

        # Notebook
        self.winPreferences.notebook = gtk.Notebook()
        self.winPreferences.notebook.set_scrollable(True)
        self.winPreferences.notebook.set_size_request(580, 330)
        self.winPreferences.notebook.set_properties(group_id=0, tab_vborder=0, tab_hborder=1, tab_pos=gtk.POS_LEFT)
        self.winPreferences.notebook.popup_enable()
        self.winPreferences.notebook.show()

        # Create tabs and append to notebook
        self.gtkPreferencesIntegration()
        self.gtkPreferencesPlugins()
        self.gtkPreferencesWWS()

        # Close button
        self.winPreferences.CloseButton = gtk.Button(stock=gtk.STOCK_CLOSE)
        self.winPreferences.CloseButton.set_size_request(90, 40)
        self.winPreferences.CloseButton.connect('clicked', lambda b: self.gtkPreferencesQuit())

        # Glue it all together
        self.winPreferences.fixed.put(self.winPreferences.notebook, 10,10)
        self.winPreferences.fixed.put(self.winPreferences.CloseButton, 490, 350)
        self.winPreferences.add(self.winPreferences.fixed)
        self.winPreferences.show_all()
        return True

    def configSetButton(self, Type, Section, Option, Value, revert=False):

        if revert == True:
            Value = self.revertBool(Value.get_active())
        else:
            Value = Value.get_active()

        try:
            self.Config[Section][Option] = Value
            #print("SET to "+str(Value))
        except Exception as e:
            print(_("Error setting configuration variable:")+" "+Section+"->"+Option+" = \""+str(Value)+"\". "+_("Error")+": "+str(e))

    def revertBool(self, boolean):
        if boolean == "False" or boolean == False:
            return True
        else:
            return False

    def configGetKey(self, Section, Key):
        if not Section in self.Config:
            return False

        if not Key in self.Config[Section]:
            return False

        if self.Config[Section][Key] == "false" or self.Config[Section][Key] == "False":
            return False

        return self.Config[Section][Key]

     
    def gtkPreferencesIntegration(self):
        # "General" preferences
        Path = os.path.expanduser("~/")

        GeneralPreferences = gtk.Fixed()
        Label1 = gtk.Label(_("File managers popup menu integration"))
        Label1.set_alignment (0, 0)
        Label1.show()

        # Filemanagers

        # ==== Dolphin, Konqueror
        Dolphin = gtk.CheckButton("Dolphin, Konqueror (KDE)")
        self.Dolphin = Dolphin
        Dolphin.connect("pressed", subgetcore.filemanagers.KDEService, self, Path)
        Dolphin.set_sensitive(True)

        if not self.dictGetKey(self.Config['filemanagers'], 'kde') == False:
            Dolphin.set_active(1)

        # ==== Nautilus
        Nautilus = gtk.CheckButton("Nautilus (GNOME)")
        Nautilus.connect("pressed", subgetcore.filemanagers.Nautilus, self, Path)
        Nautilus.set_sensitive(True)

        if not self.dictGetKey(self.Config['filemanagers'], 'gnome') == False:
            Nautilus.set_active(1)

        # ==== Thunar
        Thunar = gtk.CheckButton("Thunar (XFCE)")
        Thunar.connect("pressed", subgetcore.filemanagers.ThunarUCA, self, Path)

        if not self.dictGetKey(self.Config['filemanagers'], 'xfce') == False:
            Thunar.set_active(1)

        # ==== PCManFM
        #Thunar.set_sensitive(False)
        PCManFM = gtk.CheckButton("PCManFM (LXDE)")
        PCManFM.connect("pressed", self.configSetButton, "filemanagers", "lxde", PCManFM)
        if not self.dictGetKey(self.Config['filemanagers'], 'lxde') == False:
            PCmanFM.set_active(1)

        PCManFM.set_sensitive(False)

        GeneralPreferences.put(Label1, 10, 8)
        GeneralPreferences.put(Dolphin, 10, 26)
        GeneralPreferences.put(Nautilus, 10, 45)
        GeneralPreferences.put(Thunar, 10, 64)
        GeneralPreferences.put(PCManFM, 10, 83)

        # Video player integration
        Label2 = gtk.Label(_("Video Player settings"))
        SelectPlayer = gtk.combo_box_new_text()
        SelectPlayer.append_text(_("System's default"))
        SelectPlayer.append_text("MPlayer")
        SelectPlayer.append_text("SMPlayer")
        SelectPlayer.append_text("VLC")
        SelectPlayer.append_text("Totem")
        SelectPlayer.append_text("MPlayer2")
        SelectPlayer.append_text("KMPlayer")
        SelectPlayer.append_text("GMPlayer")
        SelectPlayer.append_text("GNOME Mplayer")
        SelectPlayer.append_text("Rhythmbox")
        SelectPlayer.connect("changed", self.defaultPlayerSelection)


        DefaultPlayer = self.dictGetKey(self.Config['afterdownload'], 'defaultplayer')

        if DefaultPlayer == False:
            SelectPlayer.set_active(0)
        else:
            DefaultPlayer = int(DefaultPlayer)
            if DefaultPlayer > -1 and DefaultPlayer < 10:
                SelectPlayer.set_active(DefaultPlayer)

        EnableVideoPlayer = gtk.CheckButton(_("Start automaticaly when program runs"))
        EnableVideoPlayer.connect("toggled", self.gtkPreferencesIntegrationPlayMovie)

        if not self.dictGetKey(self.Config['afterdownload'], 'playmovie') == False:
            EnableVideoPlayer.set_active(1)
        

        GeneralPreferences.put(Label2, 10, 118)
        GeneralPreferences.put(EnableVideoPlayer, 10, 138)
        GeneralPreferences.put(SelectPlayer, 10, 163)
        
        self.createTab(self.winPreferences.notebook, _("System integration"), GeneralPreferences)

    def configSetKey(self, Section, Option, Value):
        if not Section in self.Config:
            self.Config[Section] = dict()

        self.Config[Section][Option] = str(Value)

    def WWSDefaultLanguage(self, x, liststore, checkbox):
        """ Sets preferred language for Watch with subtitles feature """
        self.configSetKey('watch_with_subtitles', 'preferred_language', str(liststore[checkbox.get_active()][1]))
        


    def gtkPreferencesWWS(self):
        """ Watch with subtitles preferences """

        # "General" preferences
        Path = os.path.expanduser("~/")

        WWS = gtk.Fixed()
        Label1 = gtk.Label(_("\"Watch with subtitles\" settings"))
        Label1.set_alignment (0, 0)
        Label1.show()

        # Filemanagers

        # ==== Download only option
        downloadOnly = gtk.CheckButton(_("Never launch movie, just download subtitles"))
        downloadOnly.connect("pressed", self.configSetButton, 'watch_with_subtitles', 'download_only', downloadOnly, True)
        downloadOnly.set_sensitive(True)
        downloadOnly.set_active(bool(self.configGetKey('watch_with_subtitles', 'download_only')))

        # ==== Only preferred language
        only_preferred_language = gtk.CheckButton(_("Download subtitles only in preferred language"))
        only_preferred_language.connect("pressed", self.configSetButton, 'watch_with_subtitles', 'only_preferred_language', only_preferred_language, True)
        only_preferred_language.set_sensitive(True)
        only_preferred_language.set_active(bool(self.configGetKey('watch_with_subtitles', 'only_preferred_language')))

        # ==== Selection of preferred language
        Label2 = gtk.Label(_("Preferred language:"))

        liststore = gtk.ListStore(gtk.gdk.Pixbuf, str)
        languages = os.listdir("/usr/share/subget/icons/")

        preferred_language = gtk.ComboBox(liststore)
        preferred_language.set_wrap_width(4)

        preferred_language_conf = self.configGetKey('watch_with_subtitles', 'preferred_language')

        i=0
        fi=0

        for Lang in languages:
            basename, extension = os.path.splitext(Lang)

            if extension == ".xpm":
                i+=1

                pixbuf = gtk.gdk.pixbuf_new_from_file("/usr/share/subget/icons/"+basename+".xpm")
                liststore.append([pixbuf, str(basename)])
                if basename == preferred_language_conf:
                    fi=i

        preferred_language.set_active((fi-1))

        preferred_language.connect("changed", self.WWSDefaultLanguage, liststore, preferred_language)



        cellpb = gtk.CellRendererPixbuf()
        preferred_language.pack_start(cellpb, True)
        preferred_language.add_attribute(cellpb, 'pixbuf', 0)
        cell = gtk.CellRendererText()
        preferred_language.pack_start(cell, True)
        preferred_language.add_attribute(cell, 'text', 1)

        WWS.put(Label1, 10, 8)
        WWS.put(downloadOnly, 10, 25)
        WWS.put(only_preferred_language, 10, 45)
        WWS.put(Label2, 10, 80)
        WWS.put(preferred_language, 150, 75)
        #WWS.put(SelectPlayer, 10, 163)
        
        self.createTab(self.winPreferences.notebook, _("Watch with subtitles"), WWS)

    # Set connection timeouts for all plugins supporting this function
    def gtkPreferencesPlugins_Scale(self, x):
        if not "plugins" in self.Config:
            self.Config['plugins'] = dict()

        self.Config['plugins']['timeout'] = int(x.value)

    def gtkPreferencesPlugins_Sort(self, x):
        self.x.get_active()

    def gtkPreferencesPlugins(self):
        g = gtk.Fixed()
        Label = gtk.Label(_("List ordering"))
        Label.set_alignment (0, 0)

        # Sorting
        AllowSorting = gtk.CheckButton(_("Sort search results by plugins list"))
        if self.configGetKey('plugins', 'list_ordering') == "True":
            AllowSorting.set_active(1)
        else:
            AllowSorting.set_active(0)

        AllowSorting.connect("toggled", self.configSetButton, 'plugins', 'list_ordering', AllowSorting)

        # Global settings
        Label2 = gtk.Label(_("Extensions global settings"))
        adj = gtk.Adjustment(1.0, 1.0, 30.0, 1.0, 1.0, 1.0)
        adj.connect("value_changed", self.gtkPreferencesPlugins_Scale)
        scale = gtk.HScale(adj)
        scale.set_digits(0)
        scale.set_size_request(230, 40)
        scaleValue = int(self.configGetKey('plugins', 'timeout'))

        if not scaleValue == False and scaleValue > 0 and scaleValue <= 30:
            adj.set_value(scaleValue)


        Label3 = gtk.Label(_("Timeout waiting for connection")+":")
        
        # put all elements
        g.put(Label, 10, 8)
        g.put(AllowSorting, 10, 26)
        g.put(Label2, 10, 70)
        g.put(Label3, 20, 95)
        g.put(scale, 80, 115)

        self.createTab(self.winPreferences.notebook, _("Plugins"), g)


    def defaultPlayerSelection(self, widget):
        """ Select default external video playing program """
        self.Config['afterdownload']['defaultplayer'] = widget.get_active()


    def gtkPreferencesIntegrationPlayMovie(self, Widget):
        Value = Widget.get_active()
        self.Config['afterdownload']['playmovie'] = Value

        if Value == True:
            self.VideoPlayer.set_active(1)
        else:
            self.VideoPlayer.set_active(0)


    def createTab(self, widget, title, inside):
        """ This appends a new page to the notebook. """
        
        page = gtk.Label(title)
        page.show()
        
        widget.append_page(inside, page)
        widget.set_tab_reorderable(page, True)
        widget.set_tab_detachable(page, True)


    def gtkMainScreen(self,files):
        """ Main GTK screen of the application """
        #if len(files) == 1:
        #gobject.timeout_add(1, self.TreeViewUpdate)
        
        # Create a new window
        self.window = gtk.Window(gtk.WINDOW_TOPLEVEL)
        self.screen = self.window.get_screen()
        self.window.set_title(_("Download subtitles"))
        self.window.set_resizable(True)

        # make the application bigger if it will fit on screen
        if self.screen.get_width() >= 800:
            self.window.set_size_request(750, 340)

        self.window.connect("delete_event", self.delete_event)
        self.window.set_icon_from_file(self.subgetOSPath+"/usr/share/subget/icons/Subget-logo.png")

        # DRAG & DROP SUPPORT
        TARGET_STRING = 82
        TARGET_IMAGE = 83

        if os.path.isfile("/usr/bin/nautilus"):
            self.window.drag_dest_set(gtk.DEST_DEFAULT_DROP,[("text/plain", 0, TARGET_STRING),("image/*", 0, TARGET_IMAGE)],gtk.gdk.ACTION_COPY)
        else:
            self.window.drag_dest_set(0, [], 0)

        self.window.connect("drag_motion", self.motion_cb)
        self.window.connect("drag_drop", self.drop_cb)
        self.window.connect("drag_data_received", self.drag_data_received)

        ############# Menu #############
        mb = gtk.MenuBar()
        icon_theme = gtk.icon_theme_get_default()

        # Shortcuts
        agr = gtk.AccelGroup()
        self.window.add_accel_group(agr)

        # "File" menu
        fileMenu = gtk.Menu()
        fileMenuItem = gtk.MenuItem(_("File"))
        fileMenuItem.set_submenu(fileMenu)
        mb.append(fileMenuItem)

        # "Tools" menu
        toolsMenu = gtk.Menu()
        toolsMenuItem = gtk.MenuItem(_("Tools"))
        toolsMenuItem.set_submenu(toolsMenu)
        mb.append(toolsMenuItem)

        # "Plugins list"
        pluginMenu = gtk.ImageMenuItem(_("Plugins"), agr)
        key, mod = gtk.accelerator_parse("<Control>P")
        pluginMenu.add_accelerator("activate", agr, key,mod, gtk.ACCEL_VISIBLE)
        pluginMenu.connect("activate", self.gtkPluginMenu)

        try:
            image = gtk.Image()
            image.set_from_file(self.subgetOSPath+"/usr/share/subget/icons/plugin.png")
            pluginMenu.set_image(image)
        except gobject.GError as exc:
            True

        toolsMenu.append(pluginMenu)

        # "About"
        infoMenu = gtk.ImageMenuItem(_("About Subget"), agr) # gtk.STOCK_CDROM
        key, mod = gtk.accelerator_parse("<Control>I")
        infoMenu.add_accelerator("activate", agr, key,mod, gtk.ACCEL_VISIBLE)
        infoMenu.connect("activate", self.gtkAboutMenu)

        try:
            pixbuf = icon_theme.load_icon("dialog-information", 16, 0)
            image = gtk.Image()
            image.set_from_pixbuf(pixbuf)
            infoMenu.set_image(image)
        except gobject.GError as exc:
            True

        toolsMenu.append(infoMenu)

        # "Clear"
        clearMenu = gtk.ImageMenuItem(_("Clear list"))
        clearMenu.connect("activate", lambda b: self.cleanUpResults())

        try:
            image = gtk.Image()
            image.set_from_stock(gtk.STOCK_CLEAR, 2)
            clearMenu.set_image(image)
        except gobject.GError as exc:
            True


        toolsMenu.append(clearMenu)

        # Adding files to query
        settingsMenu = gtk.ImageMenuItem(gtk.STOCK_PREFERENCES)
        settingsMenu.connect("activate", self.gtkPreferences)
        toolsMenu.append(settingsMenu)

        # Adding files to query
        openMenu = gtk.ImageMenuItem(gtk.STOCK_ADD, agr)
        key, mod = gtk.accelerator_parse("<Control>O")
        openMenu.add_accelerator("activate", agr, key,mod, gtk.ACCEL_VISIBLE)
        openMenu.connect("activate", self.gtkSelectVideo)
        fileMenu.append(openMenu)

        # Search
        find = gtk.ImageMenuItem(gtk.STOCK_FIND, agr)
        key, mod = gtk.accelerator_parse("<Control>F")
        find.add_accelerator("activate", agr, key, mod, gtk.ACCEL_VISIBLE)
        find.connect("activate", self.gtkSearchMenu)
        fileMenu.append(find)

        # Exit position in menu
        exit = gtk.ImageMenuItem(gtk.STOCK_QUIT, agr)
        key, mod = gtk.accelerator_parse("<Control>Q")
        exit.add_accelerator("activate", agr, key, mod, gtk.ACCEL_VISIBLE)
        exit.connect("activate", gtk.main_quit)
        fileMenu.append(exit)

        ############# End of Menu #############
        #self.fixed = gtk.Fixed()

        self.liststore = gtk.ListStore(gtk.gdk.Pixbuf, str, str, str)
        self.treeview = gtk.TreeView(self.liststore)


        # column list
        self.tvcolumn = gtk.TreeViewColumn(_("Language"))
        self.tvcolumn1 = gtk.TreeViewColumn(_("Name of release"))
        self.tvcolumn2 = gtk.TreeViewColumn(_("Server"))

        # Resizable attributes
        self.tvcolumn1.set_resizable(True)
        self.tvcolumn2.set_resizable(True)

        self.treeview.append_column(self.tvcolumn)
        self.treeview.append_column(self.tvcolumn1)
        self.treeview.append_column(self.tvcolumn2)


        self.cellpb = gtk.CellRendererPixbuf()
        #self.cellpb.set_property('pixbuf', pixbuf)

        self.cell = gtk.CellRendererText()
        self.cell1 = gtk.CellRendererText()
        self.cell2 = gtk.CellRendererText()

        # add the cells to the columns - 2 in the first
        self.tvcolumn.pack_start(self.cellpb, False)

        self.tvcolumn.set_cell_data_func(self.cellpb, self.cell_pixbuf_func)
        #self.tvcolumn.pack_start(self.cell, True)
        self.tvcolumn1.pack_start(self.cell1, True)
        self.tvcolumn2.pack_start(self.cell2, True)
        self.tvcolumn1.set_attributes(self.cell1, text=1)
        self.tvcolumn2.set_attributes(self.cell2, text=2)

        # make treeview searchable
        self.treeview.set_search_column(1)

        # Allow sorting on the column
        self.tvcolumn1.set_sort_column_id(1)
        self.tvcolumn2.set_sort_column_id(2)


        # Create buttons
        self.DownloadButton = gtk.Button(stock=gtk.STOCK_GO_DOWN)
        self.DownloadButton.set_label(_("Download"))
        image = gtk.Image()
        image.set_from_stock("gtk-go-down", gtk.ICON_SIZE_BUTTON)
        self.DownloadButton.set_image(image)
        self.DownloadButton.set_size_request(100, 40)
        #self.fixed.put(self.DownloadButton, 490, 205) # put on fixed

        self.DownloadButton.connect('clicked', lambda b: self.GTKDownloadSubtitles())

        # Videoplayer checkbutton
        self.VideoPlayer = gtk.CheckButton(_("Start video player"))
        if not self.dictGetKey(self.Config['afterdownload'], 'playmovie') == False: # TRUE, playmovie active
            self.VideoPlayer.set_active(1)
        else:
            self.VideoPlayer.set_active(0)
            self.VideoPlayer.hide()

        #self.fixed.put(self.VideoPlayer, 10, 205)

        # Cancel button
        self.CancelButton = gtk.Button(stock=gtk.STOCK_CLOSE)
        self.CancelButton.set_size_request(90, 40)
        self.CancelButton.connect('clicked', lambda b: gtk.main_quit())
        #self.fixed.put(self.CancelButton, 390, 205) # put on fixed

        # scrollbars
        scrolled_window = gtk.ScrolledWindow()
        scrolled_window.set_shadow_type(gtk.SHADOW_ETCHED_IN)
        scrolled_window.set_border_width(0)
        scrolled_window.set_size_request(600, 200)
        scrolled_window.set_policy(gtk.POLICY_AUTOMATIC, gtk.POLICY_AUTOMATIC)
        scrolled_window.add(self.treeview)

        #self.fixed.put(scrolled_window, 0, 0)
        #self.fixed.set_border_width(0)
        
        vbox = gtk.VBox(False, 0)
        vbox.set_border_width(0)
        vbox.pack_start(mb, False, False, 0)
        vbox.pack_start(scrolled_window, True, True, 0)
        buttonsAlligned = gtk.Alignment(0, 1, 0, 0)
        #vbox.pack_start(self.fixed, False, False, 0)

        hbox = gtk.HBox(False, 5)
        hbox.pack_start(buttonsAlligned)
        hbox.pack_start(self.VideoPlayer, False, False, 5)
        hbox.pack_start(self.CancelButton, False, False, 5)
        hbox.pack_end(self.DownloadButton, False, False, 5)
        vbox.pack_start(hbox, False, False, 8)

        self.window.add(vbox)
        # create a TreeStore with one string column to use as the model
        

        self.window.show_all()

        #else:
            #    print(_("Sorry, GUI mode is not fully available yet."))

    ##### DRAG & DROP SUPPORT #####
    def motion_cb(self, wid, context, x, y, time):
        context.drag_status(gtk.gdk.ACTION_COPY, time)
        return True
    
    def drop_cb(self, wid, context, x, y, time):
        if context.targets:
            wid.drag_get_data(context, context.targets[0], time)
            return True
        return False

    
    def drag_data_received(self, img, context, x, y, data, info, time):
        """ Receive dropped data, parse and call plugins """

        if data.format == 8:
            Files = data.data.replace('\r', '').split("\n")
            self.files = list()

            for File in Files:
                File = File.replace("file://", "")

                if os.path.isfile(File):
                    self.files.append(File)

            context.finish(True, False, time)
            self.TreeViewUpdate()
                
        

    ##### END OF DRAG & DROP SUPPORT #####

    def graphicalMode(self, files):
            """ Detects operating system and load GTK GUI """
            self.files = files

            self.gtkMainScreen(files)
            gobject.timeout_add(50, self.TreeViewUpdate)
            gtk.main()

    def shellMode(self, files):
        """ Works in shell mode, searching, downloading etc..."""
        global plugins, action

        # just find all matching subtitles and print it to console
        if action == "list":
            for Plugin in self.pluginsList:
                State = self.plugins[Plugin]

                if type(State).__name__ != "module":
                    continue

                Results = self.plugins[Plugin].language = language
                Results = self.plugins[Plugin].download_list(files)

                if Results == None:
                    continue

                for Result in Results:
                    for Movie in Result:
                        try:
                            if Movie.has_key("title"):
                                print(Movie['domain']+"|"+Movie['lang']+"|"+Movie['title'])
                        except AttributeError:
                            continue


        elif action == "first-result":
                Found = False
                preferredData = False

        for File in files:
            for Plugin in plugins:
                exec("State = self.plugins[\""+Plugin+"\"]")

                if type(State).__name__ != "module":
                    continue

                fileToList = list()
                fileToList.append(File)

                Results = self.plugins[Plugin].language = language
                Results = self.plugins[Plugin].download_list(fileToList)

                if Results != None:
                    if type(Results[0]).__name__ == "dict":
                        continue
                    else:
                        if Results[0][0]["lang"] == language:
                            FileTXT = File+".txt"
                            exec("DLResults = self.plugins[\""+Plugin+"\"].download_by_data(Results[0][0]['data'], FileTXT)")
                            print(_("Subtitles saved to")+" "+str(DLResults))
                            Found = True
                            break
                        elif preferredData != None:
                            continue
                        else:
                            preferredData = Results[0][0]
                 
        if Found == False and preferredData == True:
            FileTXT = File+".("+str(preferredData['lang'])+").txt"
            exec("DLResults = plugins[\""+Plugin+"\"].download_by_data(prefferedData['data'], FileTXT)")
            print(_("Subtitles saved to")+" "+str(DLResults)+", "+_("but not in your preferred language"))

if __name__ == "__main__":
    SubgetMain = SubGet()
    SubgetMain.main()
