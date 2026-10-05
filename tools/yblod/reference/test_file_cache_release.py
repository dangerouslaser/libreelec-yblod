import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import file_cache_release as cache


class FileCacheReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/"evidence.bin";self.data=b"evidence retained\x00"*5000
        self.path.write_bytes(self.data);self.sha=hashlib.sha256(self.data).hexdigest()

    def calls(self):
        stack=__import__("contextlib").ExitStack();self.addCleanup(stack.close)
        sync=stack.enter_context(mock.patch.object(cache.os,"fsync"))
        advice=stack.enter_context(mock.patch.object(cache.os,"posix_fadvise",create=True))
        stack.enter_context(mock.patch.object(cache.os,"POSIX_FADV_DONTNEED",4,create=True))
        stack.enter_context(mock.patch.object(cache.os,"O_NOFOLLOW",getattr(cache.os,"O_NOFOLLOW",0),create=True))
        return sync,advice

    def test_verified_order_readonly_evidence_and_no_eviction_claim(self):
        sync,advice=self.calls();events=[]
        sync.side_effect=lambda fd:events.append(("sync",fd))
        advice.side_effect=lambda fd,*args:events.append(("advice",fd,args))
        result=cache.release_verified_file(self.path,self.sha,len(self.data))
        self.assertEqual([e[0] for e in events],["sync","advice"])
        self.assertEqual(events[0][1],events[1][1]);self.assertEqual(events[1][2],(0,0,4))
        self.assertTrue(result["dontneed_advice_submitted"]);self.assertFalse(result["eviction_verified"])
        self.assertEqual(self.path.read_bytes(),self.data)

    def test_mismatch_strict_types_and_symlinks_never_sync_or_advise(self):
        sync,advice=self.calls();link=self.path.with_name("link");link.symlink_to(self.path)
        for path,sha,size in ((self.path,"0"*64,len(self.data)),(self.path,self.sha,len(self.data)+1),
                              (self.path,self.sha,True),(self.path,self.sha,float(len(self.data))),
                              (self.path,self.sha.upper(),len(self.data)),(link,self.sha,len(self.data))):
            with self.assertRaises(ValueError):cache.release_verified_file(path,sha,size)
        sync.assert_not_called();advice.assert_not_called();self.assertEqual(self.path.read_bytes(),self.data)

    def test_sync_failure_prevents_advice_and_preserves_data(self):
        sync,advice=self.calls();sync.side_effect=OSError("sync failure")
        with self.assertRaises(OSError):cache.release_verified_file(self.path,self.sha,len(self.data))
        advice.assert_not_called();self.assertEqual(self.path.read_bytes(),self.data)

    def test_advice_failure_explicit_and_descriptor_closed(self):
        sync,advice=self.calls();advice.side_effect=OSError("advice failure")
        original=cache.os.close
        with mock.patch.object(cache.os,"close",wraps=original) as close:
            with self.assertRaises(OSError):cache.release_verified_file(self.path,self.sha,len(self.data))
            close.assert_called_once()
        sync.assert_called_once();self.assertEqual(self.path.read_bytes(),self.data)

    def test_modified_during_sync_no_advice(self):
        sync,advice=self.calls();sync.side_effect=lambda fd:self.path.write_bytes(b"changed by external writer")
        with self.assertRaisesRegex(ValueError,"during sync"):
            cache.release_verified_file(self.path,self.sha,len(self.data))
        advice.assert_not_called()

    def test_unsupported_explicit_no_fallback(self):
        with mock.patch.object(cache.os,"posix_fadvise",None,create=True):
            with self.assertRaises(NotImplementedError):cache.release_verified_file(self.path,self.sha,len(self.data))
        self.assertEqual(self.path.read_bytes(),self.data)

    def test_growing_writer_reads_at_most_declared_bytes_plus_one(self):
        sync,advice=self.calls();sizes=[]
        def growing_read(fd,size):
            sizes.append(size)
            return b"x"*size
        with mock.patch.object(cache.os,"read",side_effect=growing_read):
            with self.assertRaisesRegex(ValueError,"grew beyond"):
                cache.release_verified_file(self.path,self.sha,len(self.data))
        self.assertEqual(sum(sizes),len(self.data)+1)
        sync.assert_not_called();advice.assert_not_called()
        self.assertEqual(self.path.read_bytes(),self.data)


if __name__=="__main__":unittest.main()
