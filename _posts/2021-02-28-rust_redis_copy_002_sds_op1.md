---
layout: default
title: 我想用rust抄写redis 002 - sds基本操作
permalink: /rust-redis-copy/002-sds-op-basic
categories: [redis, rust, 源码分析]
tags: [redis, rust, 源码分析]
---

```c
// redis/src/sds.h
​
#define SDS_TYPE_5  0
#define SDS_TYPE_8  1
#define SDS_TYPE_16 2
#define SDS_TYPE_32 3
#define SDS_TYPE_64 4
#define SDS_TYPE_MASK 7
#define SDS_TYPE_BITS 3
#define SDS_HDR_VAR(T,s) struct sdshdr##T *sh = (void*)((s)-(sizeof(struct sdshdr##T)));
#define SDS_HDR(T,s) ((struct sdshdr##T *)((s)-(sizeof(struct sdshdr##T))))
#define SDS_TYPE_5_LEN(f) ((f)>>SDS_TYPE_BITS)
```

**SDS_TYPE_5/8/16/32/64** 分别标识 sdshdr5/8/16/32/64 这几种Header；

**SDS_TYPE_MASK** 用于与flags字段做位运算提取有效值；

**SDS_TYPE_BITS** 定义了flags中有效的位数，只有 sdshdr5 会用到，第12行的 SDS_TYPE_5_LEN 就是用于将 sdshdr5 的flags字段右移 SDS_TYPE_BITS 位取出字符串长度；

rust没有对应 #define 的宏，不过可以定义相应的常量，没打算支持sdshdr5，故和sdshdr5相关的代码都不抄：

```rust
const SDS_TYPE_8: u8 = 1;
const SDS_TYPE_16: u8 = 2;
const SDS_TYPE_32: u8 = 3;
const SDS_TYPE_64: u8 = 4;
const SDS_TYPE_MASK: u8 = 7;
```

**SDS_HDR_VAR** 用于定义变量sh，值为通过sds计算出的Header位置：

```c
SDS_HDR_VAR(8,s);
// 相当于
struct sdshdr8 *sh = (void*)((s)-(sizeof(struct sdshd8)));
```

rust(1.50.0)对应的宏：

```rust
// 使用unsafe块后无法像C语言版本那样暴露sh变量，
// 不过这样定义该宏使用起来更加优雅
macro_rules! SDS_HDR_VAR {
    ($sds_hdr:ty, $s:expr) => {
        unsafe {
            &*($s.0.offset(-(std::mem::size_of::<$sds_hdr>() as isize)) as *const $sds_hdr)
        }
    }
}
​
#[test]
fn test_sds_hdr_var_macro() {
    let h = SdsHdr8{
        len: 0,
        alloc: 0,
        flags: 0,
        buf: [],
    };
    let p = (&h as *const SdsHdr8) as *const i8;
    let s = unsafe{Sds(p.offset(size_of::<SdsHdr8>() as isize))};
    let sh = SDS_HDR_VAR!(SdsHdr8, s);
    println!("{}", sh.len);
    assert_eq!(h.len, sh.len);
}
```

**SDS_HDR** 和 **SDS_HDR_VAR** 的差别是 SDS_HDR 只计算出Header起始位置，而 SDS_HDR_VAR 计算出Header起始位置并赋值给变量sh；上面rust定义的 SDS_HDR_VAR 宏其实是 SDS_HDR；借助rust的类型自动推导能力，只用一个宏也足够方便了，不过还是采用函数实现，毕竟宏定义、使用看起来都很晦涩：

```rust
impl<T: Sub<Output=T> + Into<u64> + Copy> SdsHdr<T> {
    // same as
    // #define SDS_HDR(T,s) ((struct sdshdr##T *)((s)-(sizeof(struct sdshdr##T))))
    #[inline]
    fn sds_hdr(sds: &Sds) -> &Self{
        unsafe {
            &*(sds.0.offset(-(std::mem::size_of::<Self>() as isize)) as *const Self)
        }
    }
​
    #[inline]
    fn mut_sds_hdr(sds: &Sds) -> &mut Self{
        unsafe {
            &mut *(sds.0.offset(-(std::mem::size_of::<Self>() as isize)) as *mut Self)
        }
    }
​
    #[inline]
    fn sds_len(&self) -> u64 {
        self.len.into()
    }
​
    #[inline]
    fn sds_alloc(&self) -> u64 {
        self.alloc.into()
    }
​
    // same as
    // inline size_t sdsavail(const sds s)
    #[inline]
    fn sds_avail(&self) -> u64 {
        (self.alloc - self.len).into()
    }
}
```

T需要加上泛型约束 **Sub<Output=T> + Into<u64> + Copy** ，如果rust支持 T: u8|u16|u32|u64 这样的写法会简单明了很多；

Sub 是sds_avail方法里字段相减必须的（self.alloc - self.len ）；

泛型字段默认不是Copy的，故需要手动加上，不然不能通过&self访问字段；

Into将来自不同Header字段里的u8/u16/u32/u64都转成u64返回，redis中返回的是size_t，rust对应的是usize，最初写时也是返回usize的，但rust拒绝编译，原因是u16/u32/u64并未实现Into<usize>，细想这是合理的，因为usize在不同的机器大小不一，比如在32位机和u32相等、在64位机和u64相等，redis返回size_t并不严谨，因为5种Header中，sdshdr64的len/alloc字段类型为u64，转成size_t返回有可能被截断，应该选用5种类型中范围最大的u64，当然实际应用中redis很少会运行在非64位机，而且单个字符串数据也几乎不会超过4G。

SdsHdr里的方法基本和sds.h里的函数一一对应，不过对外使用的是Sds类型，需要将方法实现在Sds上：

```rust
impl Sds {
    #[inline]
    fn flags(&self) -> u8 {
        unsafe {
            (*self.0.offset(-1) as u8) & SDS_TYPE_MASK
        }
    }
​
    // same as
    // inline size_t sdslen(const sds s)
    #[inline]
    fn len(&self) -> u64 {
        match self.flags() {
            SDS_TYPE_8 => SdsHdr8::sds_hdr(self).sds_len(),
            SDS_TYPE_16 => SdsHdr16::sds_hdr(self).sds_len(),
            SDS_TYPE_32 => SdsHdr32::sds_hdr(self).sds_len(),
            SDS_TYPE_64 => SdsHdr64::sds_hdr(self).sds_len(),
            flags => unimplemented!("flags unknown: {}", flags),
        }
    }
    
    // same as
    // inline void sdssetlen(sds s, size_t newlen)
    // but mark unsafe
    #[inline]
    unsafe fn set_len_uncheck(&mut self, new_len: u64) {
        match self.flags() {
            SDS_TYPE_8 => SdsHdr8::mut_sds_hdr(self).len = new_len as u8,
            SDS_TYPE_16 => SdsHdr16::mut_sds_hdr(self).len = new_len as u16,
            SDS_TYPE_32 => SdsHdr32::mut_sds_hdr(self).len = new_len as u32,
            SDS_TYPE_64 => SdsHdr64::mut_sds_hdr(self).len = new_len as u64,
            flags => unimplemented!("flags unknown: {}", flags)
        };
    }
    
    // same as
    // inline size_t sdsavail(const sds s)
    #[inline]
    fn alloc(&self) -> u64 {
        match self.flags() {
            SDS_TYPE_8 => SdsHdr8::sds_hdr(self).sds_alloc(),
            SDS_TYPE_16 => SdsHdr16::sds_hdr(self).sds_alloc(),
            SDS_TYPE_32 => SdsHdr32::sds_hdr(self).sds_alloc(),
            SDS_TYPE_64 => SdsHdr64::sds_hdr(self).sds_alloc(),
            flags => unimplemented!("flags unknown: {}", flags)
        }
    }
    ...其他雷同，故省略...
}
```

每个方法里都有相同的match，显得有点啰嗦，trait对象可以解决这个问题，但trait对象运行时会涉及堆上分配内存，有损性能；每个方法里的match相当于trait对象的动态分发了。

可以用宏来避免4种Header需要重复写4次相同逻辑测试用例的毛病：

```rust
#[cfg(test)]
mod test {
    use super::*;
​
    macro_rules! test_sds_base {
        ($kind:ident, $flag:expr) => {
            let hdr = $kind {
            len: 0,
            alloc: 0,
            _flags: $flag,
            _buf: []
        };
        let p = (&hdr as *const $kind) as *const i8;
        unsafe {
            let mut sds = Sds(p.offset(std::mem::size_of_val(&hdr) as isize));
            assert_eq!(sds.len(), 0, "{} init len assert fail", stringify!($kind));
            assert_eq!(sds.alloc(), 0, "{} init alloc assert fail", stringify!($kind));
            assert_eq!(sds.avail(), 0, "{} init avail assert fail", stringify!($kind));
​
            sds.set_len_uncheck(1);
            assert_eq!(sds.len(), 1, "{} set_len_uncheck len assert fail", stringify!($kind));
            assert_eq!(sds.alloc(), 0, "{} set_len_uncheck alloc assert fail", stringify!($kind));
            // cannot call avail()
​
            sds.set_alloc_uncheck(2);
            assert_eq!(sds.len(), 1, "{} set_alloc_uncheck len assert fail", stringify!($kind));
            assert_eq!(sds.alloc(), 2, "{} set_alloc_uncheck alloc assert fail", stringify!($kind));
            assert_eq!(sds.avail(), 1, "{} set_alloc_uncheck avail assert fail", stringify!($kind));
​
            sds.inc_len_uncheck(1);
            assert_eq!(sds.len(), 2, "{} inc_len_uncheck len assert fail", stringify!($kind));
            assert_eq!(sds.alloc(), 2, "{} inc_len_uncheck alloc assert fail", stringify!($kind));
            assert_eq!(sds.avail(), 0, "{} inc_len_uncheck avail assert fail", stringify!($kind));
        }
        };
    }
​
    #[test]
    fn test_all_sds_basic() {
        test_sds_base!(SdsHdr8, SDS_TYPE_8);
        test_sds_base!(SdsHdr16, SDS_TYPE_16);
        test_sds_base!(SdsHdr32, SDS_TYPE_32);
        test_sds_base!(SdsHdr64, SDS_TYPE_64);
    }
}
```

宏定义时$kind的类型是ident（标识符），按理应该选ty（类型），但ty会导致在结构体初始化处报语法错误，看来ty只能用在需要“纯类型”的地方。

这个场景下用宏确实优雅些，不过有个缺点，一旦测试不通过，错误信息里显示的是宏展开后的行号和代码，只好在代码里输入一堆错误提示（assert_eq!后面的参数）；

SdsHdr里的flags/buf字段只是用来占位的，改成_flags/_buf，避免编译器dead_code警告。

完整代码 <https://github.com/iiibui/redis-rust-copy/blob/main/src/sds.rs>

> https://mp.weixin.qq.com/s?__biz=MzIxNzE5NDUyNQ==&mid=2247483676&idx=1&sn=34ec4931298afd31f3a94c9699ce2a1b


上一篇 [我想用rust抄写redis 001 - sds定义](https://gobuild.tech/rust-redis-copy/001-sds)