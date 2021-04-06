---
layout: default
title: 我想用rust抄写redis 000 - zmalloc
permalink: /rust-redis-copy/000-zmalloc
categories: [redis, rust, 源码分析]
tags: [redis, rust, 源码分析]
---

# redis通过zmalloc分配内存

  - 封装tcmalloc/jemalloc/系统内存分配器，跨平台

  - 可获取分配的最大可用内存大小，

  - 如malloc_size(malloc(9)) == 16

  - 内存使用统计

---------------------------------------------

```sh
#rustc --version

>rustc 1.50.0 (cb75ad5db 2021-02-10)
```

## rust分配内存例子

<https://doc.rust-lang.org/std/alloc/fn.alloc.html>

```
use std::alloc::{alloc, dealloc, Layout}; 

unsafe {

    let layout = Layout::new::<u16>();

    let ptr = alloc(layout);

    *(ptr as *mut u16) = 42;

    assert_eq!(*(ptr as *mut u16), 42); 

    dealloc(ptr, layout); 

}
```

rust内存分配api还未稳定，尽管可以自由分配内存了，但未提供类似malloc_size的API，nightly版Global分配器返回NonNull<[u8]>的size目前和传入的Layout的size相等。

> 相关issue：
>
> - [Remove usable_size APIs](https://github.com/rust-lang/wg-allocators/issues/17)
>
> - [Replace MemoryBlock with NonNull<[u8]>](https://github.com/rust-lang/wg-allocators/issues/61)

## 采用系统API进行内存分配

```rust
extern "C" {
    fn malloc(size: usize) -> *const u8;
    fn free(ptr: *const u8);
    fn realloc(ptr: *const u8, size: usize) -> *const u8;
}
```

malloc_size不是所以操作系统都支持的，函数名也可能不同，要条件编译

```rust
#[cfg(target_os = "macos")]
extern "C" {
    fn malloc_size(ptr: *const i8) -> usize;
}

#[cfg(target_os = "macos")]
unsafe fn zmalloc_size(ptr: *const i8) -> usize {
    malloc_size(ptr)
}

#[cfg(target_os = "linux")]
extern "C" {
    fn malloc_usable_size(ptr: *const i8) -> usize;
}

#[cfg(target_os = "linux")]
unsafe fn zmalloc_size(ptr: *const i8) -> usize {
    malloc_usable_size(ptr)
}
```

实现其他分配内存的函数最终都会调用的 void *ztrymalloc_usable(size_t size, size_t *usable)，用于记录实际分配内存大小的usable改用NonNull包裹的胖指针返回 ，要区分开分配失败和申请0字节内存的情况，故需要Option包裹返回值

```rust
#[cfg(any(target_os = "macos", target_os = "linux"))]
unsafe fn ztrymalloc_usable(size: usize) -> Option<NonNull<[i8]>> {
    let mut p = malloc(size);
    if p.is_null() {
        return None;
    }

    // NonNull::slice_from_raw_parts() unstable
    let slice = core::ptr::slice_from_raw_parts(p, zmalloc_size(p));
    Some(NonNull::new_unchecked(slice as *mut [i8]))
}

#[test]
fn test_zmalloc_size() {
    unsafe {
        let p = ztrymalloc_usable(9).unwrap();
        println!("usable size: {}", p.as_ref().len());  // p.len() unstable
    }
}
```

不支持malloc_size的系统返回的内存大小就是申请的内存大小

```rust
#[cfg(not(any(target_os = "macos", target_os = "linux")))]
unsafe fn ztrymalloc_usable(size: usize) -> Option<NonNull<[i8]>> {
    let mut p = malloc(size);
    if p.is_null() {
        return None;
    }
    // NonNull::slice_from_raw_parts() unstable
    let slice = core::ptr::slice_from_raw_parts(p, size);
    Some(NonNull::new_unchecked(slice as *mut [i8]))
}
```

不支持malloc_size的系统如果要像C语言版本额外加PREFIX_SIZE记录可参考

```rust
let prefix_size = std::mem::size_of::<usize>();
let p = malloc(size + prefix_size);
let p = if p.is_null() {
    p
} else {
    *(p as *mut usize) = size;
    p.offset(prefix_size as isize)
};
```

redis很多数据结构都有容量的，故一直强调malloc_size，后面抄sds(字符串)的实现时会很自然想起malloc_size。封装tcmalloc/jemalloc和内存使用统计功能往后再关注，现重心在数据结构。

> https://mp.weixin.qq.com/s?__biz=MzIxNzE5NDUyNQ==&mid=2247483660&idx=1&sn=c24ef7f2351fa31dc195d7a207fdbaf7