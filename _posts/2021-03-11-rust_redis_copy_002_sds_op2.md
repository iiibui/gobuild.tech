---
layout: default
title: 我想用rust抄写redis 002 - sds复杂操作
permalink: /rust-redis-copy/002-sds-op-complex
categories: [redis, rust, 源码分析]
tags: [redis, rust, 源码分析]
---

目前只完成了获取Header除buf外几个字段的读取和设置操作，对“buf字段”的操作才是核心功能。

# 创建字符串

```rust
use crate::z_malloc::{
    z_free as s_free,
    z_malloc_usable as s_malloc_usable,
    z_realloc_usable as s_realloc_usable,
    z_try_malloc_usable as s_try_malloc_usable,
};

impl Sds {
    // same as
    // sds _sdsnewlen(const void *init, size_t initlen, int trymalloc)
    // but no \0 at end any more
    fn from_raw_pointer(init: *const u8, init_len: usize, try_malloc: bool) -> Self {
        if init_len == 0 {
            return Self::empty();
        }
        let sds_type = sds_req_type(init_len);
        let hdr_size = sds_hdr_size(sds_type);
        let total_size = init_len + hdr_size;
        let (sh, mut usable) = if try_malloc {
            s_try_malloc_usable(total_size)
        } else {
            s_malloc_usable(total_size)
        };
​
        if sh.is_null() {
            panic!("malloc error");
        }
​
        usable -= hdr_size;
        usable = usable.min(sds_type_max_size(sds_type));
​
        let sds = Sds(unsafe { sh.offset(hdr_size as isize) });
        match sds_type {
            SDS_TYPE_8 => {
                let hdr = SdsHdr8::mut_sds_hdr(&sds);
                hdr.len = init_len as u8;
                hdr.alloc = usable as u8;
                hdr._flags = SDS_TYPE_8;
            }
            SDS_TYPE_16 => {
                let hdr = SdsHdr16::mut_sds_hdr(&sds);
                hdr.len = init_len as u16;
                hdr.alloc = usable as u16;
                hdr._flags = SDS_TYPE_16;
            }
            SDS_TYPE_32 => {
                let hdr = SdsHdr32::mut_sds_hdr(&sds);
                hdr.len = init_len as u32;
                hdr.alloc = usable as u32;
                hdr._flags = SDS_TYPE_32;
            }
            SDS_TYPE_64 => {
                let hdr = SdsHdr64::mut_sds_hdr(&sds);
                hdr.len = init_len as u64;
                hdr.alloc = usable as u64;
                hdr._flags = SDS_TYPE_64;
            }
            _ => unreachable!(),
        }
​
        if !init.is_null() {
            unsafe {
                init.copy_to(sds.0 as *mut u8, init_len);
            }
        }
​
        sds
    }
}
```

和sds.c里的**_sdsnewlen**函数逻辑一致：根据初始长度算出能存放该长度字符串的最小尺寸的Header类型（SdsHdr8/16/32/64），然后申请Header大小 + 初始长度大小字节的内存，将底层实际分配的可用内存大小扣除Header大小后记录在alloc字段（不超出该类型Header可表示的大小），如果还传入了初始字符串内容，则将其复制到buf位置；

对外提供的几个创建字符串的函数最终都会调用该函数。几点注意：

 * **s_try_malloc_usable/s_malloc_usable**其实是z_malloc.rs里**z_try_malloc_usable/z_malloc_usable**函数的别名，返回值从**`Option<NonNull>`**改为元组，主要是元组可以把分配的内存地址和可用内存大小直接“解包”到两个变量，使用起来更加方便，当然语义可能没那么清晰了；另外申请0字节内存是未定义行为（见malloc函数的描述）。

 * 标识长度、容量的变量类型从u64改回usize，buf字段类型由i8改成u8，避免经常要用u64 as usize、i8 as u8这样繁琐的转换，因为类似场景rust标准库里都是用usize、u8；不考虑SdsHdr64在32位机返回usize可能导致数据截断这个问题（其实入参时就被截断了），因为在32位机器申请超出32位大小的内存应该是申请失败的。redis根据长度判断合适Header的sdsReqType函数里有 **#if (LONG_MAX == LLONG_MAX)** 这样的判断。

alloc字段存放的是包含长度的大小，而不是剩下可用大小，即类似java集合类型里的capacity、golang切片里的cap，但该alloc实实在在的记录了底层分配的内存大小，并不是redis根据初始长度使用某种预测策略算出来的。

对空字符串稍微做了优化：空字符串不会申请内存，所有空字符串其实都指向预先定义的**SdsHdr8**类型全局变量；redis即使初始长度为0也会分配Header大小的内存。

# 字符串修改

主要是修改后会导致字符串增长这种情况的处理逻辑：

```rust
    // same as
    // sds sdsMakeRoomFor(sds s, size_t addlen)
    fn make_room_for(&mut self, inc_len: usize) {
        let avail = self.avail();
        if avail >= inc_len {
            return;
        }
​
        let len = self.len();
        let mut new_len = len + inc_len;
        if new_len < SDS_MAX_PRE_ALLOC {
            new_len *= 2;
        } else {
            new_len += SDS_MAX_PRE_ALLOC;
        }
​
        let old_type = self.type_code();
        let new_type = sds_req_type(new_len);
        let hdr_len = sds_hdr_size(new_type);
        let mut usable = unsafe {
            let sh = self.0.offset(-(sds_hdr_size(old_type) as isize));
            if old_type == new_type && !self.is_global_empty() {
                let (new_sh, usable) = s_realloc_usable(sh, hdr_len + new_len);
                if new_sh.is_null() {
                    panic!("s_realloc_usable {} size error", hdr_len + new_len);
                }
                self.0 = new_sh.offset(hdr_len as isize);
                usable
            } else {
                let (new_sh, usable) = s_malloc_usable(hdr_len + new_len);
                if new_sh.is_null() {
                    panic!("s_malloc_usable {} size error", hdr_len + new_len);
                }
                let new_s = new_sh.offset(hdr_len as isize) as *mut u8;
                self.0.copy_to(new_s, len);
                if !self.is_global_empty() {
                    s_free(sh);
                }
​
                self.0 = new_s;
                *(new_s.offset(-1) as *mut u8) = new_type;
                self.set_len_uncheck(len);
                usable
            }
        };
​
        usable -= hdr_len;
        usable = usable.min(sds_type_max_size(new_type));
​
        unsafe { self.set_alloc_uncheck(usable); }
    }
```

和创建的主要区别是申请内存的大小：先计算出增长后的长度n，如果n还没超过1M则申请n x 2，否则申请 n + 1M；多申请是有意义的，程序中经常有连续追加字符串的场景，如果增长多少就申请多少好有可能导致多次扩容，扩容的代价是很高的：申请另外一块内存->复制原有内存块->释放原有内存块；如果扩容后Header的类型没变，则使用realloc来申请，尽可能避免内存复制，否则使用malloc，因为Header类型变了buf部分要往后移，如果也使用realloc，虽然可能避免底层重新分配新的内存块，但这样底层也会进行一次无用的内存复制；

另外扩容时如果当前sds为空字符串则不能用realloc，因为空字符串是全局的，不能对其释放内存，这导致空字符串的处理和redis不同：后者创建时尽管只向底层申请了Header大小的内存，但底层极可能会多分配的，这样redis空字符串修改时可能不会扩容，前者相当于延迟分配内存，申请的内存大小是追加长度的两倍；

至于为什么是多申请一倍呢？应该是根据经验来的，golang用append函数给切片追加元素时如果导致扩容也是采取类似策略。

make_room_for这个函数的使用示例：

```rust
    // same as
    // sds sdscatlen(sds s, const void *t, size_t len)
    unsafe fn push_from_raw_pointer(&mut self, ptr: *const u8, len: usize) {
        if len == 0 {
            return;
        }
        let old_len = self.len();
        self.make_room_for(len);
        ptr.copy_to(self.0.offset(old_len as isize) as *mut u8, len);
        self.set_len_uncheck(old_len + len);
    }
​
    pub fn push_str(&mut self, s: &str) -> &mut Self {
        unsafe {
            self.push_from_raw_pointer(s.as_ptr(), s.len());
            self
        }
    }
​
    pub fn push_slice(&mut self, s: &[u8]) -> &mut Self {
        unsafe {
            self.push_from_raw_pointer(s.as_ptr(), s.len());
            self
        }
    }
```

# 字符串销毁

实现**Drop trait**让rust所有权规则来自动释放内存，释放内存时通过buf位置计算内存块起始位置；空字符串是全局共享的，drop时需要跳过。

```rust
impl Drop for Sds {
    // same as
    // void sdsfree(sds s)
    fn drop(&mut self) {
        if !self.is_global_empty() {
            unsafe {
                s_free(self.0.offset(-(sds_hdr_size(self.type_code()) as isize)));
            }
        }
    }
}
```

# 字符串的其他处理函数

sds兼容c字符串，c标准库里的字符串处理函数都可以使用，虽然rust版的sds也有差不多的内存布局，但总不能也使用c版本的处理函数吧，目前的做法是转成切片或&str，转换不涉及堆内存分配，开销很少，不能对外转成String，因为String会对buf拥有所有权，在String销毁时将导致程序崩溃，崩溃的直接原因不是二次释放，而是buf并非内存块的起始地址（buf前面的Header才是该块内存的起始地址），这也是转换成&str时使用forget的原因，转换成&str的方式比较别扭：裸指针->String->&String->*String->String->&str，经过中间的*String才能脱离所有权控制，不然即使在unsafe模式也是编译不过的。

```rust
    pub fn as_slice(&self) -> &[u8] {
        unsafe {
            let slice_ptr = std::ptr::slice_from_raw_parts(self.0, self.len());
            &*slice_ptr
        }
    }
​
    pub fn as_mut_slice(&self) -> &mut [u8] {
        unsafe {
            let slice_ptr = std::ptr::slice_from_raw_parts(self.0, self.len());
            &mut *(slice_ptr as *mut [u8])
        }
    }
​
    // may be illegal utf8 string
    pub fn as_str_uncheck(&self) -> &str {
        unsafe {
            let len = self.len();
            let s = String::from_raw_parts(self.0 as *mut u8, len, len);
            let fake = &*(&s as *const String);
            std::mem::forget(s);
            fake
        }
    }
```

另外还实现了到切片的解引用，my_string[0]和my_string.as_slice()[0]是等价的：

```rust
impl Deref for Sds {
    type Target = [u8];
​
    fn deref(&self) -> &Self::Target {
        self.as_slice()
    }
}
```

而支持println宏打印则由以下代码实现：

```rust
impl Display for Sds {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.as_str_uncheck())
    }
}
```

字符串相等比较由以下代码实现：

```rust
impl PartialEq for Sds {
    fn eq(&self, other: &Self) -> bool {
        self.as_slice().cmp(other.as_slice()) == Ordering::Equal
    }
}
​
impl Eq for Sds {}
```

大小比较由以下代码实现：

```rust
impl PartialOrd for Sds {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        self.as_slice().partial_cmp(other.as_slice())
    }
}
​
impl Ord for Sds {
    fn cmp(&self, other: &Self) -> Ordering {
        self.as_slice().cmp(other.as_slice())
    }
}
```

最终用法示例：

```rust
    #[test]
    fn test_sample() {
        let mut my_string = Sds::from_str("Hello World!");
        println!("{}", my_string);
​
        let buf = ['A' as u8, 'B' as u8, 'C' as u8];
        my_string = Sds::from_slice(&buf); // auto free before value
        println!("{} of len {}", my_string, my_string.len());
​
        my_string = Sds::empty(); // auto free before value
        println!("{}", my_string.len());
​
        my_string.push_str("Hello ").push_str("World!");
        println!("{}", my_string);
​
        let my_string2 = my_string.clone();
        println!("{} == {}", my_string, my_string2);
​
        my_string = Sds::from_str(" Hello World! ");
        let my_string_trim = my_string.as_str_uncheck().trim();
        println!("{}", my_string_trim);
        println!("{} {}", my_string.starts_with(&[' ' as u8]), my_string_trim.starts_with('H'));
    }
```

完整代码 <https://github.com/iiibui/redis-rust-copy/blob/main/src/sds.rs>

> http://mp.weixin.qq.com/s?__biz=MzIxNzE5NDUyNQ==&mid=2247483681&idx=1&sn=ee8074762efe6aa90364e45a146edaee


上一篇 [我想用rust抄写redis 002 - sds基本操作](/rust-redis-copy/002-sds-op-base)