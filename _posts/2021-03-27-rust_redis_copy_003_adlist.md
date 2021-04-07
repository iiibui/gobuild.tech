---
layout: default
title: 我想用rust抄写redis 003 - adlist双向链表
permalink: /rust-redis-copy/003-adlist
categories: [redis, rust, 源码分析]
tags: [redis, rust, 源码分析]
---

![adlist structure](/imgs/rust-redis-copy-003-adlist/adlist.png)

# adlist（A generic doubly linked list）：

```c
typedef struct listNode {
    struct listNode *prev;
    struct listNode *next;
    void *value;
} listNode;
​
typedef struct list {
    listNode *head;
    listNode *tail;
    void *(*dup)(void *ptr);
    void (*free)(void *ptr);
    int (*match)(void *ptr, void *key);
    unsigned long len;
} list;
```

从结构来看adlist比较简单，就一个常规的双向链表，不过实现时增删节点还是要谨慎，很容易漏掉更新前一节点的next指针或后一节点的prev指针，也容易忽略头节点或尾节点要特殊对待。

adlist和rust标准库里的**LinkedList**很像，LinkedList也是双向链表，LinkedList支持泛型，数据内容通常由LinkedList持有所有权：

```rust
// rust 1.50
pub struct LinkedList<T> {
    head: Option<NonNull<Node<T>>>,
    tail: Option<NonNull<Node<T>>>,
    len: usize,
    marker: PhantomData<Box<Node<T>>>,
}
​
struct Node<T> {
    next: Option<NonNull<Node<T>>>,
    prev: Option<NonNull<Node<T>>>,
    element: T,
}
```

不过rust版本的adlist只是对着redis的版本来实现，节点通过裸指针连在一起，节点数据也定义为泛型：

```rust
pub struct List<T: Copy + PartialEq> {
    head: *const Node<T>,
    tail: *const Node<T>,
    len: usize,
    value_clone: Option<fn(T)->T>,
    value_drop: Option<fn(T)>,
    value_equals: Option<fn(T, T)->bool>,
}
​
pub struct Node<T: Copy + PartialEq> {
    prev: *const Node<T>,
    next: *const Node<T>,
    pub value: T,
}
```

不用 **`Option<NonNull>`** 主要考虑操纵裸指针更加直观，也不用Option包裹裸指针，Option包裹裸指针后占用内存大小为两倍指针大小（指针可null，无法对None优化），节点数据类型用一个Copy（用于复制）和PartialEq（用于相等判断）约束，这样不用考虑Drop的问题，也不用考虑所有权，缺点是放复杂的数据只能用裸指针（如果只是临时存放，用借用也可以），value字段类型是T而不是*T，因为指针也是类型的一种，T也能表达指针类型。

# 创建列表：

```rust
    // same as
    // list *listCreate(void)
    pub fn new() -> Self {
        let list = Self {
            head: null(),
            tail: null(),
            len: 0,
            value_clone: None,
            value_drop: None,
            value_equals: None,
        };
​
        list
    }
```

List直接在栈上创建，这和C版本不一样，当然，后面在嵌套使用时如果不方便可能会再做修改。


# 在列表头或尾添加元素：

```rust
    pub fn push_front(&mut self, value: T) -> &mut Self {
        let node = unsafe { z_malloc_of_type::<Node<T>>() as *mut Node<T> };
        if node.is_null() {
            panic!("z_malloc_of_type fail");
        }
​
        let node = unsafe { &mut *node };
        node.value = value;
        node.prev = null();
​
        if self.len == 0 {
            self.head = node;
            self.tail = node;
            node.next = null();
        } else {
            node.next = self.head;
            unsafe { (*(self.head as *mut Node<T>)).prev = node; }
            self.head = node;
        }
        self.len += 1;
        self
    }
​
    pub fn push_back(&mut self, value: T) -> &mut Self {
        let node = unsafe { z_malloc_of_type::<Node<T>>() as *mut Node<T> };
        if node.is_null() {
            panic!("z_malloc_of_type fail");
        }
​
        let node = unsafe { &mut *node };
        node.value = value;
        if self.len == 0 {
            self.head = node;
            self.tail = node;
            node.prev = null();
            node.next = null();
        } else {
            node.prev = self.tail;
            node.next = null();
            unsafe { (*(self.tail as *mut Node<T>)).next = node; }
            self.tail = node;
        }
        self.len += 1;
        self
    }
```

unsafe rust写起来比C麻烦得多；可以看出列表头的prev和列表尾的next指向null，即列表并非循环列表。

# 查找元素：

```rust
    // same as
    // listNode *listSearchKey(list *list, void *key)
    pub fn search(&self, value: T) -> *const Node<T> {
        for n in self.iter() {
            unsafe {
                if let Some(value_equals) = self.value_equals {
                    if value_equals((*n).value, value) {
                        return n;
                    }
                } else if (*n).value == value {
                    return n;
                }
            }
        }
​
        null()
    }
    
    pub fn iter(&self) -> It<T> {
        It{next: self.head, direction: ItDirection::HeadToTail}
    }
```

利用迭代器来遍历列表查找元素，迭代器实现和C版本完全一样，只是rust可以用for来迭代。

```rust
impl<T: Copy + PartialEq> Iterator for It<T> {
    type Item = *const Node<T>;
​
    fn next(&mut self) -> Option<Self::Item> {
        let current = self.next;
        if current.is_null() {
            return None;
        }
​
        match self.direction {
            ItDirection::HeadToTail => {
                unsafe { self.next = (*current).next; }
            }
            ItDirection::TailToHead => {
                unsafe { self.next = (*current).prev; }
            }
        }
​
        Some(current)
    }
}


删除节点：

    // same as
    // void listDelNode(list *list, listNode *node)
    pub unsafe fn remove(&mut self, node: *mut Node<T>) {
        let node = &mut *node;
        // if prev is null, it is the head node
        if node.prev.is_null() {
            self.head = node.next;
        } else {
            (*(node.prev as *mut Node<T>)).next = node.next;
        }
​
        // if next is null, it is the tail node
        if node.next.is_null() {
            self.tail = node.prev;
        } else {
            (*(node.next as *mut Node<T>)).prev = node.prev;
        }
​
        if let Some(value_drop) = self.value_drop {
            value_drop(node.value);
        }
​
        z_free(node as *mut Node<T> as *const u8);
        self.len -= 1;
    }
```

# 清空列表：

```rust
    // same as
    // void listEmpty(list *list)
    // unsafe cuz free_value
    pub unsafe fn clear(&mut self) {
        let len = self.len;
        let mut current = self.head;
        for _ in 0..len {
            let next = (*current).next;
            if let Some(value_drop) = self.value_drop {
                value_drop((*current).value);
            }
            z_free(current as *const u8);
            current = next;
        }
​
        self.head = null();
        self.tail = null();
        self.len = 0;
    }
```

销毁列表很简单，因为List是在栈上分配的，无需手动释放List占用的内存，只需要销毁列表节点即可，实现Drop让rust自动销毁：

```rust
impl<T: Copy + PartialEq> Drop for List<T> {
    // same as
    // void listRelease(list *list)
    fn drop(&mut self) {
        unsafe { self.clear(); }
    }
}
```

最终示例代码：

```rust
#[test]
fn test_basic() {
    let mut list = List::new();
    assert!(list.is_empty());
​
    list.push_front(1);
    assert!(!list.is_empty());
    unsafe {
        assert_eq!((*list.first()).value, 1);
    }
​
    list.push_back(2);
    unsafe {
        assert_eq!((*list.last()).value, 2);
        assert_eq!(list.len(), 2);
    }
​
    let elements: Vec<_> = list.iter()
        .map(|n| unsafe{(*n).value})
        .collect();
    assert_eq!(elements.as_slice(), &[1, 2]);
​
    unsafe {
        assert_eq!((*list.get(0)).value, 1);
        assert_eq!((*list.get(-1)).value, 2);
        assert!(list.get(2).is_null());
        assert!(list.get(-3).is_null());
    }
​
    list.move_head_to_tail();
    unsafe {
        assert_eq!((*list.first()).value, 2);
        assert_eq!((*list.last()).value, 1);
    }
​
    list.move_tail_to_head();
    unsafe {
        assert_eq!((*list.first()).value, 1);
        assert_eq!((*list.last()).value, 2);
    }
​
    let mut other = list.clone();
    other.move_tail_to_head();
    list.push_back(3).append(&mut other);
    assert!(other.is_empty());
​
    let elements: Vec<_> = list.iter()
        .map(|n| unsafe{(*n).value})
        .collect();
    assert_eq!(elements.as_slice(), &[1, 2, 3, 2, 1]);
​
    unsafe { list.remove(list.search(3) as *mut Node<_>); }
    let elements: Vec<_> = list.iter()
        .map(|n| unsafe{(*n).value})
        .collect();
    assert_eq!(elements.as_slice(), &[1, 2, 2, 1]);
​
    list.move_head_to_tail();
    let elements: Vec<_> = list.rev_iter()
        .map(|n| unsafe{(*n).value})
        .collect();
    assert_eq!(elements.as_slice(), &[1, 1, 2, 2]);
​
    unsafe {
        list.insert_node(list.first() as *mut Node<_>, 3, false);
        list.insert_node(list.last() as *mut Node<_>, 3, true);
    }
    let elements: Vec<_> = list.rev_iter()
        .map(|n| unsafe{(*n).value})
        .collect();
    assert_eq!(elements.as_slice(), &[3, 1, 1, 2, 2, 3]);
}
```

rust并不建议使用LinkedList，因为对缓存不友好，不过链表还是有其优势的，比如删除节点的复杂度很低。

总结：对外暴露Node容易导致Node被多次释放内存或Node内存被释放后还在使用，此外Node没有记录挂在哪个List的，难免会误将属于A列表的节点传入B列表去删除；操作裸指针非常繁琐。总的来说就是“unrusty“，后面根据其他模块的使用场景来修改。

完整代码 <https://github.com/iiibui/redis-rust-copy/blob/main/src/ad_list.rs>

> https://mp.weixin.qq.com/s?__biz=MzIxNzE5NDUyNQ==&mid=2247483689&idx=1&sn=744348c9b897147b67681aaac58b6a69