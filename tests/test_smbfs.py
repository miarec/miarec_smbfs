# coding: utf-8
from __future__ import absolute_import
from __future__ import unicode_literals

import io
import platform
import unittest
import uuid

import smb.base

import fs.errors
import fs.path
import fs.test
from fs.enums import ResourceType
from fs.subfs import ClosingSubFS
from miarec_smbfs import SMBFS

from . import utils
from .utils import mock


@unittest.skipUnless(utils.DOCKER, "docker service unreachable.")
class TestDirectTcp(fs.test.FSTestCases, unittest.TestCase):
    DIRECT_TCP = True

    def make_fs(self):
        self.OPEN_URL = utils.get_connection_url(direct_tcp=self.DIRECT_TCP)
        self.dir = fs.path.join('data', uuid.uuid4().hex)
        self.smbfs = fs.open_fs(self.OPEN_URL)
        self.smbfs.makedirs(self.dir, recreate=True)
        return self.smbfs.opendir(self.dir, factory=ClosingSubFS)

    @unittest.skip("the filesystem is not case sensitive")
    def test_case_sensitive(self):
        super().test_case_sensitive()

    def test_connection_error(self):
        with utils.mock.patch('miarec_smbfs.smbfs.SMBFS.NETBIOS') as n:
            n.queryIPForName = utils.mock.MagicMock(return_value = ("TE"))
            self.assertRaises(
                fs.errors.CreateFailed,
                fs.open_fs, 'msmb://8.8.8.8?timeout=1'
            )

    def test_write_denied(self):
        _fs = fs.open_fs(utils.get_connection_url(anonymous=True, dir='data', direct_tcp=self.DIRECT_TCP))
        self.assertRaises(
            fs.errors.PermissionDenied,
            _fs.openbin, '/test.txt', 'w'
        )

    def test_openbin_root(self):
        _fs = fs.open_fs(self.OPEN_URL)
        self.assertRaises(
            fs.errors.ResourceNotFound,
            _fs.openbin, '/abc'
        )
        self.assertRaises(
            fs.errors.PermissionDenied,
            _fs.openbin, '/abc', 'w'
        )

    def test_openbin_error(self):
        self.fs.touch("abc")
        with mock.patch.object(self.smbfs, "_new_connection", side_effect=IOError):
            self.assertRaises(fs.errors.OperationFailed, self.fs.openbin, "abc")

    def test_makedir_root(self):
        _fs = fs.open_fs(self.OPEN_URL)
        self.assertRaises(
            fs.errors.PermissionDenied,
            _fs.makedir, '/abc'
        )

    def test_removedir_root(self):
        _fs = fs.open_fs(self.OPEN_URL)

        scandir = utils.mock.MagicMock(return_value=iter([]))
        with utils.mock.patch.object(_fs, 'scandir', scandir):
            self.assertRaises(
                fs.errors.PermissionDenied,
                _fs.removedir, '/data'
            )

    def test_seek(self):
        self.fs.writetext('foo.txt', 'Hello, World !')

        with self.fs.openbin('foo.txt') as handle:
            self.assertRaises(ValueError, handle.seek, -2, 0)
            self.assertRaises(ValueError, handle.seek, 2, 2)
            self.assertRaises(ValueError, handle.seek, -2, 12)

            self.assertEqual(handle.seek(2, 1), 2)
            self.assertEqual(handle.seek(-1, 1), 1)
            self.assertEqual(handle.seek(-2, 1), 0)

        self.fs.remove('foo.txt')

    def test_makedir(self):
        super().test_makedir()
        self.fs.touch('abc')
        self.assertRaises(
            fs.errors.DirectoryExpected,
            self.fs.makedir, '/abc/def'
        )
        self.assertRaises(
            fs.errors.ResourceNotFound,
            self.fs.makedir, '/spam/bar'
        )
        self.assertRaises(
            fs.errors.DirectoryExists,
            self.fs.delegate_fs().makedir, '/'
        )
        self.assertRaises(
            fs.errors.DirectoryExists,
            self.fs.delegate_fs().makedir, 'data'
        )

    def test_move(self):
        super().test_move()
        self.fs.touch('a')
        self.fs.touch('b')
        self.assertRaises(
            fs.errors.DirectoryExpected,
            self.fs.move, 'a', 'b/a'
        )
        self.assertRaises(
            fs.errors.DestinationExists,
            self.fs.delegate_fs().move,
            fs.path.join(self.dir, 'a'),
            fs.path.join(self.dir, 'b'),
        )

    def test_openbin(self):
        super().test_openbin()
        self.fs.makedir('spam')
        self.assertRaises(
            fs.errors.FileExpected,
            self.fs.openbin, 'spam'
        )
        self.fs.touch('abc.txt')
        self.assertRaises(
            fs.errors.DirectoryExpected,
            self.fs.openbin, 'abc.txt/def.txt', 'w'
        )

    def test_removedir(self):
        super().test_removedir()
        self.assertRaises(
            fs.errors.RemoveRootError,
            self.fs.delegate_fs().removedir, '/'
        )

    def test_scanshares(self):
        share = next(self.fs.delegate_fs().scandir('/', ['basic', 'access']))
        self.assertEqual(share.name, 'data')
        #self.assertEqual(share.get('access', 'uid'), "S-1-5-21-708263368-3365369569-291063048-1000")
        self.assertTrue(share.get('access', 'uid').startswith("S-1-5-21"))

    def test_getinfo_root(self):
        self.assertEqual(self.fs.delegate_fs().gettype('/'), ResourceType.directory)
        self.assertEqual(self.fs.delegate_fs().getsize('/'), 0)

    def test_info_access_smb1(self):
        self.fs.writetext('test.txt', 'This is a test')
        _smb = self.fs.delegate_fs()._smb
        with utils.mock.patch.object(_smb, '_getSecurity', new=_smb._getSecurity_SMB1):
            try:
                info = self.fs.getinfo('test.txt', namespaces=['access'])
            except smb.base.NotReadyError:
                self.fail("getinfo(..., ['access']) raised an error")
            try:
                list(self.fs.scandir('/', namespaces=['access']))
            except smb.base.NotReadyError:
                self.fail("scandir(..., ['access']) raised an error")

    def test_getinfo_smb(self):
        self.fs.writetext('test.txt', 'This is a test')
        info = self.fs.getinfo('test.txt', namespaces=['basic', 'smb'])
        self.assertFalse(info.get('smb', 'hidden'))
        self.assertFalse(info.get('smb', 'system'))

    def test_openbin_w_readinto(self):
        with self.fs.openbin("abc", "w") as f:
            self.assertRaises(IOError, f.readinto, io.BytesIO())

    def test_download_error(self):
        self.fs.makedir("/abc")
        self.assertRaises(fs.errors.FileExpected, self.fs.download, "/abc", io.BytesIO())
        self.assertRaises(fs.errors.ResourceNotFound, self.fs.download, "/def", io.BytesIO())
        self.assertRaises(fs.errors.ResourceNotFound, self.fs.download, "/def/ghi", io.BytesIO())

    def test_upload_root(self):
        _fs = fs.open_fs(self.OPEN_URL)
        self.assertRaises(fs.errors.PermissionDenied, _fs.upload, "/abc", io.BytesIO())

    def test_upload_error(self):
        self.fs.makedir("/abc")
        self.assertRaises(fs.errors.FileExpected, self.fs.upload, "/abc", io.BytesIO())
        self.assertRaises(fs.errors.ResourceNotFound, self.fs.upload, "/def/ghi", io.BytesIO())


@unittest.skipIf(platform.system() == "Windows", "Cannot test NETBIOS on Windows")
@unittest.skipUnless(utils.DOCKER, "docker service unreachable.")
class TestNETBIOS(TestDirectTcp):
    DIRECT_TCP = False


@unittest.skipIf(platform.system() == "Windows", "Cannot test NETBIOS on Windows")
@unittest.skipUnless(utils.DOCKER, "docker service unreachable.")
class TestSMBFSConnection(unittest.TestCase):

    user = "rio"
    pasw = "letsdance"

    def open_smbfs(self, host_token, port=None, direct_tcp=False):
        return SMBFS(host_token, self.user, self.pasw, port=port, direct_tcp=direct_tcp)

    def assert_connected(self, smbfs):
        try:
            smbfs.touch("data/hello.txt")
        except fs.errors.OperationFailed:
            self.fail("could not create a file")

    def test_hostname(self):
        smbfs = self.open_smbfs("SAMBAALPINE")
        self.assert_connected(smbfs)

    def test_ip(self):
        smbfs = self.open_smbfs("127.0.0.1")
        self.assert_connected(smbfs)

    @mock.patch.object(SMBFS, 'NETBIOS', mock.MagicMock())
    def test_ip_direct_tcp(self):
        smbfs = self.open_smbfs("127.0.0.1", direct_tcp=True)
        self.assert_connected(smbfs)
        SMBFS.NETBIOS.queryIPforName.assert_not_called()
        SMBFS.NETBIOS.queryName.assert_not_called()

    @mock.patch.object(SMBFS, 'NETBIOS', mock.MagicMock())
    def test_hostname_and_ip(self):
        smbfs = self.open_smbfs(("SAMBAALPINE", "127.0.0.1"))
        self.assert_connected(smbfs)
        SMBFS.NETBIOS.queryIPforName.assert_not_called()
        SMBFS.NETBIOS.queryName.assert_not_called()

    @mock.patch.object(SMBFS, 'NETBIOS', mock.MagicMock())
    def test_ip_and_hostname(self):
        smbfs = self.open_smbfs(("127.0.0.1", "SAMBAALPINE"))
        self.assert_connected(smbfs)
        SMBFS.NETBIOS.queryIPforName.assert_not_called()
        SMBFS.NETBIOS.queryName.assert_not_called()

    def test_ip_and_none(self):
        smbfs = self.open_smbfs(("127.0.0.1", None))
        self.assert_connected(smbfs)

    def test_none_and_ip(self):
        smbfs = self.open_smbfs((None, "127.0.0.1"))
        self.assert_connected(smbfs)

    def test_hostname_and_none(self):
        smbfs = self.open_smbfs(("SAMBAALPINE", None))
        self.assert_connected(smbfs)

    def test_none_and_hostname(self):
        smbfs = self.open_smbfs((None, "SAMBAALPINE"))
        self.assert_connected(smbfs)

    def test_none_none(self):
        self.assertRaises(
            fs.errors.CreateFailed,
            self.open_smbfs, (None, None)
        )

    def test_none(self):
        self.assertRaises(
            fs.errors.CreateFailed,
            self.open_smbfs, None
        )

    def test_default_smb_port(self):
        smbfs = self.open_smbfs("127.0.0.1")
        self.assertEqual(smbfs._smb.sock.getpeername()[1], 139)
        self.assert_connected(smbfs)

    def test_explicit_smb_port(self):
        smbfs = self.open_smbfs(("127.0.0.1", "SAMBAALPINE"), port=utils.DIRECT_TCP_PORT, direct_tcp=True)
        self.assertEqual(smbfs._smb.sock.getpeername()[1], utils.DIRECT_TCP_PORT)
        self.assert_connected(smbfs)
