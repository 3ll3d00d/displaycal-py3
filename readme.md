Building on debian trixie
=========================

* install pyenv
* add plugin (used when building wxpython)

    git clone git://github.com/concordusapps/pyenv-implict.git ~/.pyenv/plugins/pyenv-implict
    
* install 2.7-dev and use it

    env PYTHON_CONFIGURE_OPTS="--enable-shared" pyenv install 2.7-dev
    pyenv local 2.7-dev

* install wxPython build dependencies

    sudo apt install libwxgtk3.2-dev libgtk-3-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libglut-dev libwebkitgtk-6.0-dev libsdl1.2-dev libnotify-dev libwebkit2gtk-4.0-dev libwebkit2gtk-4.1-dev

* create a venv and activate it

    virtualenv -p /home/matt/.pyenv/shims/python dc-p2
    . dc-p2/bin/activate

* install deps

    pip install dbus-python distro numpy Pillow six wheel setuptools pathlib2 attrdict

* download, build and verify wxpython

    pip download wxPython==4.0.6
    pip wheel --no-clean -v wxPython-4.0.6.tar.gz  2>&1 | tee build.log
    pip install wxPython-4.0.6-cp27-cp27mu-linux_x86_64.whl
    python -c "import wx; a=wx.App(); wx.Frame(None,title='hello world').Show(); a.MainLoop();"

